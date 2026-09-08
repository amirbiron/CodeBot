"""ניקוי צ'אנקים סמנטיים יתומים מהקולקציה ``snippet_chunks``.

למה צריך ג'וב ולא רק ניקוי בזמן מחיקה
--------------------------------------
מסלולי המחיקה מנקים את הצ'אנקים שלהם (ראו ``database/manager.py``
``delete_snippet_chunks``), אבל שני מקורות של יתומים אינם עוברים דרך קוד
אפליקציה בכלל:

1. **פקיעת סל המיחזור** נעשית ב-TTL index על ``deleted_expires_at``. מונגו
   מוחק את מסמך הקובץ בצד השרת, ואף שורת קוד שלנו לא רצה — אז אין למי
   לנקות את הצ'אנקים.
2. **גרסאות שהוחלפו** — שמירת גרסה חדשה אינה מכבה את הגרסה הקודמת, ולכן
   בלי הכלל שכאן כל גרסה היסטורית נשארת מאונדקסת. הצינור בחיפוש זורק אותה
   רק אחרי ``$vectorSearch``, כלומר אחרי שכבר תפסה מקומות ב-ANN.

בנוסף, הג'וב מנקה את מה שכבר הצטבר בפרודקשן לפני שהניקוי בזמן מחיקה נכנס.

הגדרת "יתום" זהה לכלל שהחיפוש אוכף (``search_engine._build_hybrid_search_pipeline``):
צ'אנק שייך לקובץ רק אם הקובץ קיים, פעיל, **והוא הגרסה האחרונה** של
``(user_id, file_name)`` לפי ``version`` יורד ואז ``updated_at`` ואז ``_id``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Tuple

logger = logging.getLogger(__name__)

try:  # Structured logging events
    from observability import emit_event
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields: Any) -> None:
        return None

# גודל הבאץ' למחיקה ולשליפות ``$in``. שומר על מסמכי בקשה קטנים בהרבה
# מתקרת ה-16MB של מונגו, גם כשמספר הצ'אנקים גדל פי כמה.
DEFAULT_BATCH_SIZE = 500


def _get_raw_db():
    try:
        from services.semantic_embedding_settings import get_raw_db_best_effort
        return get_raw_db_best_effort()
    except Exception:
        return None


def _get_collection(raw_db, name: str):
    try:
        return raw_db[name]
    except Exception:
        return getattr(raw_db, name, None)


def _batched(items: List[Any], size: int) -> Iterable[List[Any]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _is_object_id(value: Any) -> bool:
    """האם ה-``snippetId`` הוא ObjectId, כמו שכותב ``save_snippet_chunks``.

    מסמך עם מזהה מסוג אחר (מחרוזת, למשל, ממיגרציה ישנה) לא יימצא ב-``$lookup``
    לפי ``_id`` — כלומר ייראה יתום ויימחק. זה בדיוק סוג הכשל השקט שאסור לנו,
    ולכן מסמכים כאלה נספרים ומדווחים ולעולם לא נמחקים כאן.
    """
    try:
        from bson import ObjectId
    except Exception:
        # בלי bson אי אפשר להבחין — ולכן **שום דבר** אינו נחשב מזהה תקין,
        # והג'וב לא ימחק כלום. החזרת ``True`` כאן הייתה הופכת את הכשל
        # לפתוח: כל מזהה היה נכנס למסלול המחיקה בדיוק כשאין לנו יכולת
        # לאמת אותו.
        return False
    return isinstance(value, ObjectId)


def cleanup_orphan_snippet_chunks(
    *,
    batch_size: int = DEFAULT_BATCH_SIZE,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """מוחק צ'אנקים שאין להם קובץ פעיל ועדכני, ומחזיר סיכום.

    Returns:
        dict עם ``chunk_groups`` (כמה זוגות ``userId+snippetId`` נבדקו),
        ``orphan_snippets``, ``deleted_chunks``, ``skipped_non_objectid``,
        ו-``ok`` שמסמן אם הריצה הושלמה. ``ok=False`` פירושו שהריצה נעצרה
        מוקדם (אין DB / שגיאה) — ולא שאין מה לנקות.
    """
    summary: Dict[str, Any] = {
        "ok": False,
        "chunk_groups": 0,
        "orphan_snippets": 0,
        "deleted_chunks": 0,
        "skipped_non_objectid": 0,
        "ownership_mismatch": 0,
        "quarantined_no_file_name": 0,
        "dry_run": bool(dry_run),
    }

    raw_db = _get_raw_db()
    if raw_db is None:
        summary["reason"] = "no_db"
        return summary

    chunks = _get_collection(raw_db, "snippet_chunks")
    files = _get_collection(raw_db, "code_snippets")
    if chunks is None or files is None:
        summary["reason"] = "missing_collection"
        return summary

    # --- 1. אילו (userId, snippetId) מיוצגים בכלל בצ'אנקים ------------------
    group_pipeline = [
        {"$group": {
            "_id": {"userId": "$userId", "snippetId": "$snippetId"},
            "chunks": {"$sum": 1},
        }},
    ]
    try:
        # ``allowDiskUse`` כדי שהשלב הזה לא ייפול על תקרת ה-100MB של
        # ``$group`` כשהקולקציה גדלה — הוא רץ **לפני** כל ה-batching, ולכן
        # כשלון בו עוצר את הניקוי כולו. סטאבים בטסטים לא בהכרח מקבלים את
        # הפרמטר, ולכן יש נפילה חזרה לקריאה בלעדיו.
        try:
            groups = list(chunks.aggregate(group_pipeline, allowDiskUse=True))
        except TypeError:
            groups = list(chunks.aggregate(group_pipeline))
    except Exception as exc:
        logger.warning("snippet_chunks janitor: group failed: %s", exc)
        emit_event("snippet_chunks_cleanup_error", severity="warn", stage="group", error=str(exc))
        summary["reason"] = "group_failed"
        return summary

    pairs: List[Tuple[Any, Any]] = []
    for g in groups:
        key = (g or {}).get("_id") or {}
        user_id = key.get("userId")
        snippet_id = key.get("snippetId")
        if snippet_id is None:
            continue
        if not _is_object_id(snippet_id):
            summary["skipped_non_objectid"] += 1
            continue
        pairs.append((user_id, snippet_id))

    summary["chunk_groups"] = len(pairs)
    if not pairs:
        summary["ok"] = True
        return summary

    snippet_ids = [sid for _u, sid in pairs]

    # --- 2. אילו סניפטים בכלל קיימים, ומה השם/הגרסה שלהם -------------------
    existing: Dict[Any, Dict[str, Any]] = {}
    try:
        for batch in _batched(snippet_ids, batch_size):
            cursor = files.find(
                {"_id": {"$in": batch}},
                {"user_id": 1, "file_name": 1, "is_active": 1, "version": 1},
            )
            for doc in cursor:
                if isinstance(doc, dict) and doc.get("_id") is not None:
                    existing[doc["_id"]] = doc
    except Exception as exc:
        logger.warning("snippet_chunks janitor: lookup failed: %s", exc)
        emit_event("snippet_chunks_cleanup_error", severity="warn", stage="lookup", error=str(exc))
        summary["reason"] = "lookup_failed"
        return summary

    # --- 3. מי הגרסה הפעילה האחרונה לכל (user_id, file_name) ---------------
    # אותו סדר בדיוק שהצינור בחיפוש משתמש בו, כדי ששתי ההגדרות לא ייסחפו.
    wanted: List[Tuple[Any, str]] = []
    for doc in existing.values():
        if not bool(doc.get("is_active", False)):
            continue
        file_name = doc.get("file_name")
        if file_name:
            wanted.append((doc.get("user_id"), str(file_name)))
    wanted = list({w for w in wanted})

    latest: Dict[Tuple[Any, str], Any] = {}
    if wanted:
        user_ids = list({u for u, _f in wanted})
        file_names = list({f for _u, f in wanted})
        try:
            for batch in _batched(file_names, batch_size):
                rows = files.aggregate([
                    {"$match": {
                        "is_active": True,
                        "user_id": {"$in": user_ids},
                        "file_name": {"$in": batch},
                    }},
                    {"$sort": {
                        "user_id": 1,
                        "file_name": 1,
                        "version": -1,
                        "updated_at": -1,
                        "_id": -1,
                    }},
                    {"$group": {
                        "_id": {"user_id": "$user_id", "file_name": "$file_name"},
                        "latest": {"$first": "$_id"},
                    }},
                ])
                for row in rows:
                    key = (row or {}).get("_id") or {}
                    latest[(key.get("user_id"), str(key.get("file_name")))] = row.get("latest")
        except Exception as exc:
            logger.warning("snippet_chunks janitor: latest-version scan failed: %s", exc)
            emit_event(
                "snippet_chunks_cleanup_error", severity="warn", stage="latest", error=str(exc)
            )
            summary["reason"] = "latest_failed"
            return summary

    # --- 4. מי יתום -------------------------------------------------------
    orphans_by_user: Dict[Any, List[Any]] = {}
    for user_id, snippet_id in pairs:
        doc = existing.get(snippet_id)
        if doc is None:
            keep = False  # הקובץ נמחק סופית / פקע ב-TTL
        elif not bool(doc.get("is_active", False)):
            keep = False  # הקובץ בסל המיחזור
        elif doc.get("user_id") != user_id:
            # הצ'אנק מתויג למשתמש אחד והסניפט שייך לאחר. זה לא יכול להיווצר
            # מהכתיבות שלנו (``save_snippet_chunks`` לוקח את שניהם מאותו
            # מסמך), אבל אם זה קורה — **חייבים** למחוק: הפילטר של
            # ``$vectorSearch`` הוא על ``userId`` של הצ'אנק, ולכן צ'אנק כזה
            # היה צף בתוצאות של המשתמש הלא נכון. ראו ``CRITICAL-PATTERNS.md``
            # K12. השארתו היא הסיכון, לא מחיקתו.
            keep = False
            summary["ownership_mismatch"] += 1
            emit_event(
                "snippet_chunks_ownership_mismatch",
                severity="anomaly",
                chunk_user_id=user_id,
                snippet_user_id=doc.get("user_id"),
            )
        elif not str(doc.get("file_name") or "").strip():
            # מסמך פעיל בלי שם קובץ אינו נכנס לשלב "הגרסה האחרונה", ולכן
            # ``latest`` לעולם לא יכיל אותו — והיעדר המפתח **אינו** ראיה
            # שהצ'אנקים שלו יתומים. רשומה פגומה נשמרת ומדווחת; לא נמחקת.
            keep = True
            summary["quarantined_no_file_name"] += 1
        else:
            key = (doc.get("user_id"), str(doc.get("file_name")))
            keep = latest.get(key) == snippet_id
        if not keep:
            orphans_by_user.setdefault(user_id, []).append(snippet_id)

    summary["orphan_snippets"] = sum(len(v) for v in orphans_by_user.values())
    if not orphans_by_user or dry_run:
        summary["ok"] = True
        return summary

    # --- 5. מחיקה --------------------------------------------------------
    # תמיד עם ``userId`` וגם ``snippetId``: זה מה שהאינדקס
    # ``snippet_chunks_user_snippet_idx`` משרת, וזה גם מונע מחיקה חוצת-משתמשים.
    deleted = 0
    for user_id, ids in orphans_by_user.items():
        for batch in _batched(ids, batch_size):
            try:
                result = chunks.delete_many({"userId": user_id, "snippetId": {"$in": batch}})
            except Exception as exc:
                logger.warning("snippet_chunks janitor: delete failed: %s", exc)
                emit_event(
                    "snippet_chunks_cleanup_error",
                    severity="warn",
                    stage="delete",
                    error=str(exc),
                )
                summary["deleted_chunks"] = deleted
                summary["reason"] = "delete_failed"
                return summary
            deleted += int(getattr(result, "deleted_count", 0) or 0)

    summary["deleted_chunks"] = deleted
    summary["ok"] = True

    emit_event(
        "snippet_chunks_cleanup_done",
        chunk_groups=summary["chunk_groups"],
        orphan_snippets=summary["orphan_snippets"],
        deleted_chunks=deleted,
        skipped_non_objectid=summary["skipped_non_objectid"],
        ownership_mismatch=summary["ownership_mismatch"],
        quarantined_no_file_name=summary["quarantined_no_file_name"],
    )
    if summary["skipped_non_objectid"]:
        # לא מוחקים אותם, אבל גם לא בולעים: מישהו צריך להסתכל.
        logger.warning(
            "snippet_chunks janitor: %s chunk groups have a non-ObjectId snippetId and were skipped",
            summary["skipped_non_objectid"],
        )
    return summary
