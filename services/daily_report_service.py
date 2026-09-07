"""דוח בוקר יומי — קורא ומצליב בין מקורות הניטור הקיימים.

המודול הזה **אינו מודד דבר חדש ואינו קובע שום סף חדש**. כל מספר בו נקרא
ממקור שכבר נכתב היום: ``alerts_log``, ``service_metrics``, ``slow_queries_log``,
``job_runs``, ``collStats``, Redis ‏``INFO``, ואנדפוינטים שמורים ב-PostHog.
מה שהוא כן מוסיף הוא **הצלבה** — האם אירועים ממקורות שונים נופלים באותו חלון
זמן — ו**השוואה מול אתמול**, שנשמרת באוסף קטן משלו.

שלושה עקרונות שמכתיבים את כל המבנה כאן:

1. **מקור שנכשל לקרוא אינו מקור שהחזיר אפס.** הקוראים הקיימים בריפו
   (``aggregate_alert_summary``, ``aggregate_top_endpoints``,
   ``get_pattern_statistics``) מחזירים ``0``/``[]`` גם כשה-DB לא זמין, ולכן
   אי אפשר להישען עליהם: סנאפשוט שנשמר עם אפס בגלל תקלה יגרום לדוח של מחר
   להכריז על **שיפור**. לכן כל מקור נקרא כאן ישירות ונעטף ב-:class:`SourceRead`,
   שבו כשל הוא ``ok=False`` ו-``value=None`` — ולעולם לא אפס.
2. **הדוח מדווח שינוי, לא מצב.** שורה נכנסת להודעה רק כשקרה משהו. אין שורות
   "תקין", כי שורה שנראית זהה כל יום מפסיקים לקרוא.
3. **בלי בסיס להשוואה לא ממציאים אחד.** ההשוואה דורשת את הסנאפשוט של D-1
   במפורש; "השורה האחרונה שיש" אינה תחליף, כי יום שבו ה-job לא רץ היה גורם
   להשוואה מול שלשום ולדיווח שינוי כפול.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

#: האוסף שבו נשמר סנאפשוט יומי אחד. נקרא מכאן גם על ידי
#: ``DatabaseManager._create_daily_report_indexes`` כדי שלא יהיו שני מקורות לשם.
COLLECTION_NAME = "daily_report_snapshots"

#: ‏45 יום. **ארוך בכוונה מה-TTL של המקורות** (``slow_queries_log`` — 7 ימים):
#: הסנאפשוט הוא מספרים בלבד, הוא זעיר, והוא צריך לשרוד מעבר לחלון של 30 הימים
#: שבו נשמרים הדפוסים והשגיאות המוכרים. TTL זהה למקורות היה מוחק את הבסיס
#: להשוואה לפני שהוא מספיק לשמש.
TTL_SECONDS = 45 * 24 * 60 * 60

#: כמה זמן אחורה נשמר זיכרון של "כבר ראינו את זה" — דפוסי שאילתה וסוגי שגיאות
#: ב-MCP. מול אתמול בלבד לא מספיק: דפוס שהופיע, נעלם וחזר היה מדווח כחדש פעמיים.
KNOWN_ITEMS_WINDOW_DAYS = 30

#: תקרת אורך להודעה. ‏Telegram חוסם ב-4096, וה-forwarder מוסיף כותרת משלו;
#: אותו מרווח ביטחון שנבחר ב-``services/rules_evaluator.py``.
MAX_MESSAGE_CHARS = 3800

#: חומרת ההתראה שדרכה הדוח נשלח. ``info`` לא היה מגיע: בפרודקשן
#: ``ALERT_TELEGRAM_MIN_SEVERITY=warn``, ו-``info`` נמוך ממנו.
REPORT_SEVERITY = "warn"

#: שם ההתראה. ייעודי ולא ``admin_notification``, כדי שאפשר יהיה לכוון עליו
#: כלל או ``ALERT_TELEGRAM_SUPPRESS_ALERTS`` בלי לגעת בכל הודעות האדמין.
REPORT_ALERT_NAME = "daily_morning_report"

#: התראות שאינן "אירוע" ולכן אינן פותחות חלון הצלבה: הדיפלוי נשמר בנפרד
#: (הוא החלון להצלבת קאש), והדוח עצמו נרשם ל-``alerts_log`` ואסור לו להצליב
#: מול עצמו.
_NON_EVENT_ALERT_NAMES = frozenset({"deployment_event", "admin_notification", REPORT_ALERT_NAME})

#: החומרות שנחשבות אירוע לצורך חלון ההצלבה.
_EVENT_SEVERITIES = frozenset({"critical", "error", "anomaly"})

#: האוספים שגודלם מדווח. אלה שני אוספי הלוג שתפחו בפועל, ושני אוספי
#: הניטור שנקראים כאן ממילא.
GROWTH_COLLECTIONS = ("service_metrics", "job_runs", "slow_queries_log", "alerts_log")


@dataclass(frozen=True)
class SourceRead:
    """תוצאת קריאה ממקור אחד — ערוץ כשל אחד בלבד.

    שני מצבים שנראים דומים וחייבים להיבדל, בדיוק כמו ב-
    ``services/mcp_analytics_service.EndpointResult``:

    * ``ok=True`` עם ערך ריק — נקרא בהצלחה, פשוט לא היה מה לספור.
    * ``ok=False`` — הקריאה נכשלה. ``value`` הוא ``None``, **לא** אפס.

    בלי ההבחנה הזו כשל בקריאה נשמר בסנאפשוט כאפס, ומחר הדוח מכריז על שיפור.
    """

    value: Any = None
    ok: bool = True
    error: str = ""

    @classmethod
    def failed(cls, error: str) -> "SourceRead":
        return cls(value=None, ok=False, error=str(error or "unknown"))

    def to_doc(self) -> Dict[str, Any]:
        """ייצוג לשמירה בסנאפשוט. כשל נשמר כ-``ok: False`` בלי ערכים."""
        doc: Dict[str, Any] = {"ok": bool(self.ok), "error": str(self.error or "")}
        if self.ok and isinstance(self.value, dict):
            doc.update(self.value)
        return doc


def _exc_code(exc: BaseException) -> str:
    """קוד כשל קצר לשמירה — שם המחלקה בלבד.

    ההודעה עצמה **אינה** נשמרת: היא עלולה לשאת כתובת חיבור או שם מסד, והמסמך
    הזה נקרא בדשבורד ומודבק להודעת טלגרם.
    """
    return f"exception:{type(exc).__name__}"


def ensure_utc_aware(value: Any) -> Optional[datetime]:
    """מנרמל חותמת זמן ל-UTC מודע לאזור.

    ``datetime`` נאיבי מפורש כ-**UTC**, וזו הנחה שנשענת על הכותבים בפועל:
    ``PersistentQueryProfilerService.record_slow_query_sync`` כותב
    ``datetime.utcnow()`` (``services/query_profiler_service.py``), ושאר
    האוספים כותבים ``datetime.now(timezone.utc)``. ביום שבו מישהו יחליף שם
    ל-``datetime.now()`` המקומי, חלון ההצלבה של חמש דקות יהפוך לחלון של
    שעתיים־שלוש — וזה ישתוק בלי שאף בדיקה תיפול, כי ב-CI שרץ ב-UTC שתי
    הפונקציות מחזירות אותו דבר. לכן קיימת בדיקה ייעודית שמזייפת את השעון
    ומוודאת שהכותב באמת UTC (``tests/test_daily_report_service.py``).
    """
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _non_negative_delta(later: datetime, earlier: datetime) -> timedelta:
    """הפרש זמן שלעולם אינו שלילי.

    שעונים בין מכונות אינם מסונכרנים לחלוטין, וחותמת שנכתבה "בעתיד" הייתה
    מייצרת ``timedelta`` שלילי — ואז זוג אירועים אמיתי נזרק אל מחוץ לחלון.
    """
    return max(timedelta(0), later - earlier)


def _fmt_bytes(num: Any) -> str:
    try:
        value = float(num)
    except (TypeError, ValueError):
        return "?"
    if not math.isfinite(value):
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if abs(value) < 1024.0 or unit == "GB":
            if unit == "B":
                return f"{int(value)}{unit}"
            return f"{value:.1f}{unit}"
        value /= 1024.0
    return "?"


def _fmt_signed(num: int) -> str:
    return f"+{num:,}" if num > 0 else f"{num:,}"


# --------------------------------------------------------------------------
# קוראים — אחד לכל מקור. כל אחד מחזיר SourceRead ולעולם אינו זורק החוצה.
# --------------------------------------------------------------------------


def read_alerts(coll, *, start: datetime, end: datetime) -> SourceRead:
    """ספירת התראות, דיפלויים, וחלונות ההצלבה — בקריאה אחת.

    שדה הזמן הוא ``ts_dt`` ושדה החומרה ``severity`` (נשמר lowercase) —
    שניהם נכתבים ב-``monitoring/alerts_storage.record_alert``. דרילים
    (``details.is_drill``) מוחרגים, כמו בכל אגרגציה קיימת על האוסף הזה.
    """
    try:
        cursor = coll.find(
            {"ts_dt": {"$gte": start, "$lt": end}, "details.is_drill": {"$ne": True}},
            {"ts_dt": 1, "name": 1, "severity": 1, "alert_type": 1, "endpoint": 1, "_id": 0},
        )
        critical = 0
        errors = 0
        deploy_ts: List[datetime] = []
        windows: List[Dict[str, Any]] = []
        for doc in cursor:
            ts = ensure_utc_aware(doc.get("ts_dt"))
            if ts is None:
                continue
            name = str(doc.get("name") or "")
            severity = str(doc.get("severity") or "").lower()
            alert_type = str(doc.get("alert_type") or "")
            if name == "deployment_event" or alert_type == "deployment_event":
                deploy_ts.append(ts)
                continue
            if severity == "critical":
                critical += 1
            elif severity == "error":
                errors += 1
            if severity in _EVENT_SEVERITIES and name not in _NON_EVENT_ALERT_NAMES:
                windows.append(
                    {"ts": ts, "name": name, "endpoint": str(doc.get("endpoint") or "")}
                )
        windows.sort(key=lambda item: item["ts"])
        return SourceRead(
            value={
                "critical": critical,
                "error": errors,
                "deploy_count": len(deploy_ts),
                "deploy_ts": sorted(deploy_ts),
                "alert_windows": windows,
            }
        )
    except Exception as exc:  # noqa: BLE001 — כל כשל הופך ל-ok=False, לא לאפס
        logger.warning("daily_report_read_alerts_failed", extra={"error": type(exc).__name__})
        return SourceRead.failed(_exc_code(exc))


def read_top_endpoint(coll, *, start: datetime, end: datetime) -> SourceRead:
    """ה-endpoint האיטי ביותר בחלון.

    הפייפליין נגזר מ-``monitoring/metrics_storage.aggregate_top_endpoints``:
    אותו שדה זמן (``ts``), אותה הבחנה בין ``request_agg`` מגובב לבין רשומת
    בקשה בודדת. הוא משוכפל כאן ולא נקרא משם **בכוונה**, כי המקור מחזיר
    ``[]`` גם כשה-DB נופל, ואנחנו חייבים להבדיל.
    """
    pipeline = [
        {"$match": {"ts": {"$gte": start, "$lt": end}, "type": {"$in": ["request", "request_agg"]}}},
        {
            "$project": {
                "path": {"$ifNull": ["$path", {"$ifNull": ["$handler", "unknown"]}]},
                "method": {"$ifNull": ["$method", "UNKNOWN"]},
                "count": {
                    "$cond": [{"$eq": ["$type", "request_agg"]}, {"$ifNull": ["$count", 0]}, 1]
                },
                "max_duration": {
                    "$cond": [
                        {"$eq": ["$type", "request_agg"]},
                        {"$ifNull": ["$max_duration", 0.0]},
                        {"$ifNull": ["$duration_seconds", 0.0]},
                    ]
                },
            }
        },
        {
            "$group": {
                "_id": {"path": "$path", "method": "$method"},
                "count": {"$sum": "$count"},
                "max_duration": {"$max": "$max_duration"},
            }
        },
        {"$sort": {"max_duration": -1}},
        {"$limit": 1},
    ]
    try:
        rows = list(coll.aggregate(pipeline))
        if not rows:
            return SourceRead(value={"top_slow_endpoint": None})
        row = rows[0]
        ident = row.get("_id") or {}
        return SourceRead(
            value={
                "top_slow_endpoint": {
                    "endpoint": str(ident.get("path") or "unknown"),
                    "method": str(ident.get("method") or "UNKNOWN"),
                    "max_duration": float(row.get("max_duration") or 0.0),
                    "count": int(row.get("count") or 0),
                }
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("daily_report_read_metrics_failed", extra={"error": type(exc).__name__})
        return SourceRead.failed(_exc_code(exc))


def read_slow_queries(
    coll,
    *,
    start: datetime,
    end: datetime,
    alert_windows: Sequence[Dict[str, Any]],
    correlation_window: timedelta,
    known_query_ids: Optional[Dict[str, str]] = None,
) -> SourceRead:
    """שאילתות איטיות, דפוסים והצלבה — הכול מקריאה אחת.

    ``timestamp`` נכתב על ידי ``_persist_record``, ו-``query_id`` הוא גיבוב של
    **צורת** השאילתה בלבד — הערכים מוחלפים ב-``<value>`` לפני החישוב, ולכן
    אותו דפוס עם ערכים שונים הוא אותו ``query_id``.

    האוכלוסייה אחת לשני המספרים בכוונה: גם ספירת הדפוסים וגם ההצלבה נגזרות
    מאותן רשומות, אחרת "6 מתוך 8" היה מתייחס לשתי קבוצות שונות. הנפח חסום
    ממילא בסף השנייה שהפרופיילר אוכף.
    """
    try:
        rows = list(
            coll.find(
                {"timestamp": {"$gte": start, "$lt": end}},
                {
                    "query_id": 1,
                    "collection": 1,
                    "operation": 1,
                    "timestamp": 1,
                    "execution_time_ms": 1,
                    "raw_withheld_reason": 1,
                    "_id": 0,
                },
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("daily_report_read_profiler_failed", extra={"error": type(exc).__name__})
        return SourceRead.failed(_exc_code(exc))

    window_ts = [ts for ts in (ensure_utc_aware(w.get("ts")) for w in alert_windows) if ts]
    counts: Counter = Counter()
    meta: Dict[str, Dict[str, Any]] = {}
    in_windows = 0
    outside_windows = 0
    seen_ids: Dict[str, str] = {}

    for row in rows:
        query_id = str(row.get("query_id") or "")
        if not query_id:
            continue
        counts[query_id] += 1
        ts = ensure_utc_aware(row.get("timestamp"))
        if query_id not in meta:
            meta[query_id] = {
                "query_id": query_id,
                "collection": str(row.get("collection") or "unknown"),
                "operation": str(row.get("operation") or "unknown"),
                # ניתן לניתוח רק אם הרשומה נשמרה עם הערכים האמיתיים. הדשבורד
                # מציג את ``raw_withheld_reason`` בדיוק כשאין.
                "analyzable": not bool(row.get("raw_withheld_reason")),
            }
        if ts is not None:
            seen_ids[query_id] = ts.isoformat()
            if any(_non_negative_delta(max(ts, w), min(ts, w)) <= correlation_window for w in window_ts):
                in_windows += 1
            else:
                outside_windows += 1

    top_pattern = None
    if counts:
        top_id, top_count = counts.most_common(1)[0]
        top_pattern = dict(meta.get(top_id, {"query_id": top_id}))
        top_pattern["count"] = int(top_count)

    known = dict(known_query_ids or {})
    new_patterns = [
        dict(meta[qid], count=int(counts[qid])) for qid in counts if qid not in known
    ]
    new_patterns.sort(key=lambda item: item.get("count", 0), reverse=True)

    return SourceRead(
        value={
            "total_slow": len(rows),
            "unique_patterns": len(counts),
            "top_pattern": top_pattern,
            "new_patterns": new_patterns,
            "seen_query_ids": seen_ids,
            "slow_in_alert_windows": in_windows,
            "slow_outside_alert_windows": outside_windows,
        }
    )


def read_jobs(coll, *, start: datetime, end: datetime) -> SourceRead:
    """כשלים, תקיעות, וג'ובים שרצים בהצלחה על אפס פריטים.

    ``total_items: 0`` בריצה שהסתיימה ב-``completed`` הוא בדיוק המקרה שאין
    עליו התראה: שום דבר לא נכשל, ובכל זאת שום דבר לא נעשה.
    """
    try:
        rows = list(
            coll.find(
                {"started_at": {"$gte": start, "$lt": end}},
                {"job_id": 1, "status": 1, "total_items": 1, "stuck_reported_at": 1, "_id": 0},
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("daily_report_read_jobs_failed", extra={"error": type(exc).__name__})
        return SourceRead.failed(_exc_code(exc))

    failed = 0
    stuck = 0
    zero_items: set = set()
    for row in rows:
        status = str(row.get("status") or "")
        job_id = str(row.get("job_id") or "")
        if status == "failed":
            failed += 1
        if row.get("stuck_reported_at"):
            stuck += 1
        if status == "completed" and int(row.get("total_items") or 0) == 0 and job_id:
            zero_items.add(job_id)
    return SourceRead(
        value={"failed": failed, "stuck": stuck, "zero_items_jobs": sorted(zero_items)}
    )


def read_collection_sizes(db, *, names: Iterable[str] = GROWTH_COLLECTIONS) -> SourceRead:
    """גודל האוספים דרך ``collStats`` — אותה פקודה שמסך DB Health מריץ.

    אוסף שאינו קיים מדלג בשקט: זה מצב תקין (למשל לפני הכתיבה הראשונה),
    ולא כשל של המקור כולו.
    """
    per_collection: Dict[str, Dict[str, int]] = {}
    try:
        for name in names:
            try:
                stats = db.command("collStats", name)
            except Exception:  # noqa: BLE001 — אוסף חסר אינו כשל של המקור
                continue
            per_collection[name] = {
                "count": int(stats.get("count", 0) or 0),
                "size_bytes": int(stats.get("size", 0) or 0),
            }
        return SourceRead(value={"per_collection": per_collection})
    except Exception as exc:  # noqa: BLE001
        logger.warning("daily_report_read_collstats_failed", extra={"error": type(exc).__name__})
        return SourceRead.failed(_exc_code(exc))


def read_cache(cache_stats_fn: Callable[[], Any]) -> SourceRead:
    """המונים הגולמיים של Redis — לא ה-Hit Rate המחושב.

    ``keyspace_hits``/``keyspace_misses`` הם מונים **מצטברים מאז עליית
    Redis**, ולכן ה-Hit Rate שהדשבורד מציג הוא ממוצע כל החיים. השוואה יומית
    שלו כמעט תמיד רעש. לכן נשמרים כאן המונים עצמם, ו-``compare`` גוזר מהם
    את ה-Hit Rate של היממה. ``uptime_seconds`` נשמר כדי לזהות אתחול של
    Redis — שם ההפרש חסר משמעות.
    """
    try:
        stats = cache_stats_fn()
    except Exception as exc:  # noqa: BLE001
        logger.warning("daily_report_read_cache_failed", extra={"error": type(exc).__name__})
        return SourceRead.failed(_exc_code(exc))

    if stats is None:
        return SourceRead.failed("cache_unavailable")
    if not bool(getattr(stats, "enabled", False)):
        return SourceRead.failed("cache_disabled")
    error = str(getattr(stats, "error", "") or "")
    if error:
        # ``get_cache_stats`` לעולם אינו זורק; הוא מדווח כשל בשדה ``error``
        # ומחזיר ``hit_rate=0.0``. בלי הבדיקה הזו האפס הזה היה נשמר כנתון.
        return SourceRead.failed("cache_error")
    return SourceRead(
        value={
            "keyspace_hits": int(getattr(stats, "keyspace_hits", 0) or 0),
            "keyspace_misses": int(getattr(stats, "keyspace_misses", 0) or 0),
            "uptime_seconds": int(getattr(stats, "uptime_seconds", 0) or 0),
        }
    )


def read_mcp(
    run_endpoint_fn: Callable[..., Any],
    *,
    start: datetime,
    end: datetime,
    known_error_types: Optional[Dict[str, str]] = None,
    failures_limit: int = 200,
) -> SourceRead:
    """שגיאות MCP מסוג חדש ובקשות לכלי חסר.

    האנדפוינטים השמורים ב-PostHog **אינם מקבלים טווח תאריכים** — רק
    ``limit`` — ולכן הסינון ליממה נעשה כאן, לפי ``failed_at``/``reported_at``
    שכל שורה נושאת. מסיבה זו גם נשמר ``last_refresh``: הנתון מגיע ממטמון של
    PostHog, ואסור להציג נתון בן שעה תחת הכותרת "אתמול" בלי לומר זאת.
    """
    known = dict(known_error_types or {})
    seen: Dict[str, str] = {}
    new_types: List[str] = []
    failures_today = 0
    truncated = False
    last_refresh = ""

    try:
        failures = run_endpoint_fn("ck_mcp_tool_failures", failures_limit)
    except Exception as exc:  # noqa: BLE001 — החוזה אומר שלא זורק, אבל לא נסמוך
        return SourceRead.failed(_exc_code(exc))
    if failures is None:
        return SourceRead.failed("mcp_unavailable")
    error_code = str(getattr(failures, "error_code", "") or "")
    if error_code:
        return SourceRead.failed(f"mcp:{error_code}")

    truncated = bool(getattr(failures, "has_more", False))
    last_refresh = str(getattr(failures, "last_refresh", "") or "")
    for row in list(getattr(failures, "rows", []) or []):
        if not isinstance(row, dict):
            continue
        ts = _parse_iso(row.get("failed_at"))
        error_type = str(row.get("error_type") or "").strip()
        if not error_type:
            continue
        if ts is not None:
            seen[error_type] = ts.isoformat()
            if start <= ts < end:
                failures_today += 1
                if error_type not in known and error_type not in new_types:
                    new_types.append(error_type)

    missing_today = 0
    try:
        missing = run_endpoint_fn("ck_mcp_missing_capabilities", None)
    except Exception as exc:  # noqa: BLE001
        return SourceRead.failed(_exc_code(exc))
    if missing is not None and not str(getattr(missing, "error_code", "") or ""):
        for row in list(getattr(missing, "rows", []) or []):
            if not isinstance(row, dict):
                continue
            ts = _parse_iso(row.get("reported_at"))
            if ts is not None and start <= ts < end:
                missing_today += 1

    return SourceRead(
        value={
            "new_error_types": new_types,
            "seen_error_types": seen,
            "failures_today": failures_today,
            "failures_truncated": truncated,
            "missing_capabilities_today": missing_today,
            "last_refresh": last_refresh,
        }
    )


def _parse_iso(value: Any) -> Optional[datetime]:
    """פענוח חותמת זמן שהגיעה כמחרוזת מ-PostHog."""
    if isinstance(value, datetime):
        return ensure_utc_aware(value)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return ensure_utc_aware(datetime.fromisoformat(text))
    except ValueError:
        return None


# --------------------------------------------------------------------------
# איסוף, שמירה, טעינה
# --------------------------------------------------------------------------


@dataclass
class ReportDeps:
    """התלויות שהאיסוף צורך. מוזרקות מ-``main.py``.

    הזרקה ולא ייבוא: כך הבדיקות מעבירות דמויות בלי לגעת ב-``sys.modules``,
    וכל הקריאות עוברות דרך אותו ``MongoClient`` של האפליקציה — זה שמוגדר
    ``tz_aware=True`` — במקום דרך הלקוחות הנפרדים ש-``alerts_storage`` ו-
    ``metrics_storage`` פותחים לעצמם.
    """

    alerts_coll: Any = None
    metrics_coll: Any = None
    slow_coll: Any = None
    job_runs_coll: Any = None
    snapshots_coll: Any = None
    db_for_collstats: Any = None
    cache_stats_fn: Optional[Callable[[], Any]] = None
    mcp_run_endpoint_fn: Optional[Callable[..., Any]] = None


def _roll_known(previous: Optional[Dict[str, str]], seen: Dict[str, str], *, now: datetime) -> Dict[str, str]:
    """מגלגל את סט ה"כבר ראינו" קדימה, וגוזם מה שיצא מהחלון.

    נשמר כמילון ``{מזהה: חותמת אחרונה}`` ולא כרשימה, כי בלי החותמת אי אפשר
    לגזום — והרשימה הייתה תופחת בלי גבול.
    """
    cutoff = now - timedelta(days=KNOWN_ITEMS_WINDOW_DAYS)
    merged: Dict[str, str] = {}
    for source in (previous or {}, seen):
        for key, raw_ts in (source or {}).items():
            ts = _parse_iso(raw_ts)
            if ts is None or ts < cutoff:
                continue
            existing = merged.get(key)
            if existing is None or raw_ts > existing:
                merged[key] = str(raw_ts)
    return merged


def collect_snapshot(
    *,
    day_key: str,
    day_start_utc: datetime,
    day_end_utc: datetime,
    deps: ReportDeps,
    previous: Optional[Dict[str, Any]] = None,
    correlation_window: timedelta = timedelta(minutes=5),
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """קורא את כל המקורות ומרכיב את מסמך הסנאפשוט.

    כשל של מקור אחד אינו מפיל את השאר ואינו משתיק אותם — הוא נרשם כ-
    ``ok: False`` באותו מקור בלבד. הפונקציה סינכרונית בכוונה; היא נקראת
    מתוך ``asyncio.to_thread`` כי היא נוגעת ב-Mongo, ב-Redis וב-HTTP.
    """
    now = now or datetime.now(timezone.utc)
    prev_sources = (previous or {}).get("sources") or {}

    alerts = (
        read_alerts(deps.alerts_coll, start=day_start_utc, end=day_end_utc)
        if deps.alerts_coll is not None
        else SourceRead.failed("no_collection")
    )
    alert_windows = (alerts.value or {}).get("alert_windows", []) if alerts.ok else []

    metrics = (
        read_top_endpoint(deps.metrics_coll, start=day_start_utc, end=day_end_utc)
        if deps.metrics_coll is not None
        else SourceRead.failed("no_collection")
    )

    prev_profiler = prev_sources.get("profiler") or {}
    profiler = (
        read_slow_queries(
            deps.slow_coll,
            start=day_start_utc,
            end=day_end_utc,
            alert_windows=alert_windows,
            correlation_window=correlation_window,
            known_query_ids=prev_profiler.get("known_query_ids") if prev_profiler.get("ok") else None,
        )
        if deps.slow_coll is not None
        else SourceRead.failed("no_collection")
    )

    jobs = (
        read_jobs(deps.job_runs_coll, start=day_start_utc, end=day_end_utc)
        if deps.job_runs_coll is not None
        else SourceRead.failed("no_collection")
    )

    collstats = (
        read_collection_sizes(deps.db_for_collstats)
        if deps.db_for_collstats is not None
        else SourceRead.failed("no_db")
    )

    cache = (
        read_cache(deps.cache_stats_fn)
        if deps.cache_stats_fn is not None
        else SourceRead.failed("no_cache_reader")
    )

    prev_mcp = prev_sources.get("mcp") or {}
    mcp = (
        read_mcp(
            deps.mcp_run_endpoint_fn,
            start=day_start_utc,
            end=day_end_utc,
            known_error_types=prev_mcp.get("known_error_types") if prev_mcp.get("ok") else None,
        )
        if deps.mcp_run_endpoint_fn is not None
        else SourceRead.failed("no_mcp_reader")
    )

    profiler_doc = profiler.to_doc()
    if profiler.ok:
        seen_ids = profiler_doc.pop("seen_query_ids", {})
        profiler_doc["known_query_ids"] = _roll_known(
            prev_profiler.get("known_query_ids") if prev_profiler.get("ok") else None,
            seen_ids,
            now=now,
        )
    mcp_doc = mcp.to_doc()
    if mcp.ok:
        seen_types = mcp_doc.pop("seen_error_types", {})
        mcp_doc["known_error_types"] = _roll_known(
            prev_mcp.get("known_error_types") if prev_mcp.get("ok") else None,
            seen_types,
            now=now,
        )

    return {
        "_id": day_key,
        "day_start_utc": day_start_utc,
        "day_end_utc": day_end_utc,
        "created_at": now,
        "sources": {
            "alerts": alerts.to_doc(),
            "metrics": metrics.to_doc(),
            "profiler": profiler_doc,
            "jobs": jobs.to_doc(),
            "collstats": collstats.to_doc(),
            "cache": cache.to_doc(),
            "mcp": mcp_doc,
        },
    }


def save_snapshot(coll, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """שומר את הסנאפשוט של היום ומחזיר את מה שנשמר **בפועל**.

    הכתיבה היא ``$setOnInsert`` ולא ``$set``, כלומר הכתיבה הראשונה מנצחת —
    אותו דפוס שבו ``record_alert`` מונע כפילויות. זה מה שמגן מפני שתי ריצות
    מקבילות (המתוזמנת וטריגר ידני) שהיו דורסות זו את זו: ``JobTracker``
    מונע חפיפה רק בתוך אותו תהליך, ולכן הוא אינו הגנה מספקת.

    הפונקציה קוראת את המסמך חזרה ומחזירה אותו — כך שריצה שהפסידה בכתיבה
    משווה מול הסנאפשוט שנשמר ולא מול מה שהיא עצמה חישבה. **כשל נזרק ואינו
    נבלע**: דוח שנשלח בלי סנאפשוט הופך את הדוח של מחר לשקר שקט.
    """
    day_key = snapshot["_id"]
    payload = {k: v for k, v in snapshot.items() if k != "_id"}
    coll.update_one({"_id": day_key}, {"$setOnInsert": payload}, upsert=True)
    stored = coll.find_one({"_id": day_key})
    if not stored:
        raise RuntimeError(f"snapshot_not_persisted:{day_key}")
    return stored


def load_snapshot(coll, day_key: str) -> Optional[Dict[str, Any]]:
    """טוען את הסנאפשוט של יום מסוים — לפי מפתח מפורש.

    **לא** "השורה האחרונה": יום שבו ה-job לא רץ היה גורם להשוואה מול שלשום,
    ואז שינוי של יומיים מדווח כשינוי של יום. אין מסמך ← ``None``, והדוח
    יאמר שאין בסיס להשוואה.
    """
    try:
        return coll.find_one({"_id": day_key})
    except Exception as exc:  # noqa: BLE001
        logger.warning("daily_report_load_snapshot_failed", extra={"error": type(exc).__name__})
        return None


# --------------------------------------------------------------------------
# השוואה ורינדור
# --------------------------------------------------------------------------


@dataclass
class ReportDiff:
    """מה ייכנס להודעה. שורה שאינה כאן פשוט לא תופיע."""

    day_label: str = ""
    has_baseline: bool = False
    lines: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    sections: List[str] = field(default_factory=list)

    @property
    def has_content(self) -> bool:
        return bool(self.lines or self.warnings)


def _source(snapshot: Optional[Dict[str, Any]], name: str) -> Dict[str, Any]:
    return ((snapshot or {}).get("sources") or {}).get(name) or {}


def _hit_rate(hits: int, misses: int) -> Optional[float]:
    total = hits + misses
    if total <= 0:
        return None
    return round(hits / total * 100.0, 1)


def compare(
    today: Dict[str, Any],
    yesterday: Optional[Dict[str, Any]],
    *,
    correlation_window: timedelta = timedelta(minutes=5),
) -> ReportDiff:
    """מרכיב את שורות הדוח מהסנאפשוט של היום מול זה של אתמול.

    כל שורה כאן היא **שינוי או אירוע**. מקור שנכשל מדווח "אין נתון" ולעולם
    לא "ירד" או "השתפר", ומקור בלי בסיס להשוואה מדלג על השורות שדורשות אחד.
    """
    diff = ReportDiff(day_label=str(today.get("_id") or ""), has_baseline=yesterday is not None)

    for label, key in (
        ("התראות", "alerts"),
        ("מדדים", "metrics"),
        ("שאילתות", "profiler"),
        ("jobs", "jobs"),
        ("גודל אוספים", "collstats"),
        ("קאש", "cache"),
        ("MCP", "mcp"),
    ):
        src = _source(today, key)
        if src and not src.get("ok", True):
            diff.warnings.append(f"⚠️ {label}: אין נתון ({src.get('error') or 'unknown'})")

    # --- Observability ---
    alerts = _source(today, "alerts")
    if alerts.get("ok"):
        critical = int(alerts.get("critical") or 0)
        errors = int(alerts.get("error") or 0)
        deploys = int(alerts.get("deploy_count") or 0)
        if critical or errors or deploys:
            parts = []
            if critical:
                parts.append(f"{critical} CRITICAL")
            if errors:
                parts.append(f"{errors} ERROR")
            if deploys:
                parts.append(f"{deploys} דיפלוי")
            diff.lines.append("🔭 התראות: " + " · ".join(parts))
            diff.sections.append("alerts")

    metrics = _source(today, "metrics")
    prev_metrics = _source(yesterday, "metrics")
    top = metrics.get("top_slow_endpoint") if metrics.get("ok") else None
    prev_top = prev_metrics.get("top_slow_endpoint") if prev_metrics.get("ok") else None
    if top and prev_metrics.get("ok"):
        prev_name = (prev_top or {}).get("endpoint")
        if prev_name and prev_name != top.get("endpoint"):
            diff.lines.append(
                f"   ה-endpoint האיטי ביותר השתנה: {top.get('endpoint')} "
                f"({float(top.get('max_duration') or 0.0):.1f}s) ← אתמול {prev_name}"
            )
            diff.sections.append("top_endpoint_changed")

    # --- Query Profiler ---
    profiler = _source(today, "profiler")
    prev_profiler = _source(yesterday, "profiler")
    if profiler.get("ok"):
        for pattern in list(profiler.get("new_patterns") or [])[:3]:
            suffix = " — ניתן לניתוח" if pattern.get("analyzable") else ""
            diff.lines.append(
                f"🔍 דפוס שאילתה חדש ב-{pattern.get('collection')} "
                f"({pattern.get('operation')}, {pattern.get('count')} פעמים){suffix}"
            )
            diff.sections.append("new_pattern")

        top_pattern = profiler.get("top_pattern") or {}
        prev_top_pattern = (prev_profiler.get("top_pattern") or {}) if prev_profiler.get("ok") else {}
        if top_pattern and prev_profiler.get("ok"):
            now_count = int(top_pattern.get("count") or 0)
            was_count = int(prev_top_pattern.get("count") or 0)
            # תופעת זנב: דפוס אחד שרץ מאות פעמים. יחס כולל של שאילתות חלקי
            # דפוסים היה ממסך אותה בדיוק ביום שבו היא מופיעה.
            if now_count >= 10 and now_count >= was_count * 2:
                diff.lines.append(
                    f"   הדפוס הגדול ביותר קפץ {was_count} ← {now_count} חזרות (N+1?)"
                )
                diff.sections.append("pattern_spike")

        inside = int(profiler.get("slow_in_alert_windows") or 0)
        outside = int(profiler.get("slow_outside_alert_windows") or 0)
        if inside or outside:
            minutes = int(correlation_window.total_seconds() // 60)
            diff.lines.append(
                f"   הצלבה (±{minutes} דק'): {inside} שאילתות איטיות בתוך חלונות התראה, "
                f"{outside} מחוץ"
            )
            diff.sections.append("correlation")

    # --- Cache ---
    cache = _source(today, "cache")
    prev_cache = _source(yesterday, "cache")
    if cache.get("ok") and prev_cache.get("ok"):
        uptime_now = int(cache.get("uptime_seconds") or 0)
        uptime_prev = int(prev_cache.get("uptime_seconds") or 0)
        if uptime_now < uptime_prev:
            # ‏Redis הופעל מחדש: המונים אופסו, וההפרש היה יוצא שלילי או מנופח.
            diff.lines.append("🧊 קאש: Redis הופעל מחדש — אין בסיס להשוואה יומית")
            diff.sections.append("cache_restart")
        else:
            hits = int(cache.get("keyspace_hits") or 0) - int(prev_cache.get("keyspace_hits") or 0)
            misses = int(cache.get("keyspace_misses") or 0) - int(
                prev_cache.get("keyspace_misses") or 0
            )
            rate = _hit_rate(max(0, hits), max(0, misses))
            prev_rate = _hit_rate(
                int(prev_cache.get("keyspace_hits") or 0),
                int(prev_cache.get("keyspace_misses") or 0),
            )
            if rate is not None and prev_rate is not None and abs(rate - prev_rate) >= 5.0:
                note = ""
                if rate < prev_rate and int(_source(today, "alerts").get("deploy_count") or 0):
                    note = " — היה דיפלוי באותה יממה"
                diff.lines.append(
                    f"🧊 קאש: Hit Rate יומי {rate}% (מצטבר אתמול {prev_rate}%){note}"
                )
                diff.sections.append("cache_hit_rate")

    # --- Jobs ---
    jobs = _source(today, "jobs")
    if jobs.get("ok"):
        failed = int(jobs.get("failed") or 0)
        stuck = int(jobs.get("stuck") or 0)
        if failed or stuck:
            parts = []
            if failed:
                parts.append(f"{failed} כשלים")
            if stuck:
                parts.append(f"{stuck} תקועים")
            diff.lines.append("⏱️ jobs: " + " · ".join(parts))
            diff.sections.append("jobs")
        zero_now = set(jobs.get("zero_items_jobs") or [])
        prev_jobs = _source(yesterday, "jobs")
        zero_prev = set(prev_jobs.get("zero_items_jobs") or []) if prev_jobs.get("ok") else set()
        repeated = sorted(zero_now & zero_prev)
        if repeated:
            diff.lines.append(
                "   רצו בהצלחה על אפס פריטים גם אתמול וגם היום: " + ", ".join(repeated)
            )
            diff.sections.append("zero_items")

    # --- DB growth ---
    collstats = _source(today, "collstats")
    prev_collstats = _source(yesterday, "collstats")
    if collstats.get("ok") and prev_collstats.get("ok"):
        now_map = collstats.get("per_collection") or {}
        prev_map = prev_collstats.get("per_collection") or {}
        growth_parts = []
        for name in GROWTH_COLLECTIONS:
            cur = now_map.get(name)
            was = prev_map.get(name)
            if not cur or not was:
                continue
            d_count = int(cur.get("count", 0)) - int(was.get("count", 0))
            d_size = int(cur.get("size_bytes", 0)) - int(was.get("size_bytes", 0))
            if d_count:
                growth_parts.append(f"{name} {_fmt_signed(d_count)} מסמכים ({_fmt_bytes(d_size)})")
        if growth_parts:
            diff.lines.append("🩺 DB: " + " · ".join(growth_parts))
            diff.sections.append("db_growth")

    # --- MCP ---
    mcp = _source(today, "mcp")
    if mcp.get("ok"):
        parts = []
        new_types = list(mcp.get("new_error_types") or [])
        if new_types:
            parts.append("שגיאה מסוג חדש: " + ", ".join(new_types[:3]))
        missing = int(mcp.get("missing_capabilities_today") or 0)
        if missing:
            parts.append(f"בקשת כלי חסר ×{missing}")
        if parts:
            line = "🤖 MCP: " + " · ".join(parts)
            refresh = str(mcp.get("last_refresh") or "")
            if refresh:
                # הנתון מגיע ממטמון של PostHog. בלי החותמת הזו נתון בן שעה
                # מוצג תחת הכותרת "אתמול", וזה מה שמפרק אמון בדוח.
                line += f" (נכון ל-{refresh})"
            diff.lines.append(line)
            diff.sections.append("mcp")

    return diff


def render_report(diff: ReportDiff, *, max_chars: int = MAX_MESSAGE_CHARS) -> Optional[str]:
    """מרכיב את גוף ההודעה, או ``None`` כשאין מה לדווח.

    ``None`` הוא תשובה לגיטימית ואף הנפוצה: יום שקט אינו מייצר הודעה. החיות
    של ה-job נמדדת מרשומת ההרצה ב-``job_runs`` ולא מהודעה שמעידה על עצמה.
    """
    if not diff.has_content:
        return None

    header = f"📋 דוח בוקר · {diff.day_label}"
    body: List[str] = [header]
    if not diff.has_baseline:
        body.append("ℹ️ אין בסיס להשוואה (יום ראשון של הדוח) — מוצגים אירועים בלבד")
    # אזהרות לפני שורות התוכן, ובכוונה. החיתוך למטה מוריד מהסוף, ולכן סדר
    # הפוך היה מפיל קודם כול את "⚠️ מקור X: אין נתון" — כלומר הודעה חתוכה
    # הייתה נראית כמו יום שבו כל המקורות נקראו בהצלחה. לאבד שורת תוכן זה
    # חיסרון; לאבד את הידיעה שהדוח חלקי זה להטעות.
    body.extend(diff.warnings)
    body.extend(diff.lines)

    text = "\n".join(body)
    if len(text) <= max_chars:
        return text

    # חיתוך בגבול שורה, לא באמצע מילה: הודעה חתוכה עדיפה על שליחה שנכשלת
    # בשקט מעל מגבלת Telegram.
    trimmed: List[str] = []
    used = 0
    ellipsis = "\n…"
    for line in body:
        if used + len(line) + 1 + len(ellipsis) > max_chars:
            break
        trimmed.append(line)
        used += len(line) + 1
    return "\n".join(trimmed) + ellipsis


# --------------------------------------------------------------------------
# חלונות זמן
# --------------------------------------------------------------------------


def day_key_for(now_local: datetime) -> str:
    """מפתח היום שהדוח מתאר — התאריך המקומי של היממה שהסתיימה עכשיו."""
    return (now_local.date() - timedelta(days=1)).isoformat()


def previous_day_key(day_key: str) -> str:
    """מפתח D-1. מפורש, כדי שההשוואה לא תיפול בשקט על 'האחרון שיש'."""
    return (date.fromisoformat(day_key) - timedelta(days=1)).isoformat()


def window_for(now_utc: datetime) -> tuple:
    """‏24 השעות שהסתיימו עכשיו, מעוגלות לדקה."""
    end = now_utc.replace(second=0, microsecond=0)
    return end - timedelta(days=1), end
