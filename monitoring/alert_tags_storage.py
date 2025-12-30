"""
Alert Tags Storage - שמירת תגיות ידניות להתראות.

Collection: alert_tags
מבנה מסמך:
{
    "_id": ObjectId,
    "alert_uid": str,             # מזהה ייחודי של ההתראה (Instance)
    "alert_type_name": str,       # שם התראה לתגיות גלובליות (Type)
    "alert_timestamp": datetime,  # זמן ההתראה המקורית (לשרידות log rotation)
    "tags": [str],                # רשימת תגיות
    "created_at": datetime,
    "updated_at": datetime,
    "created_by": int             # user_id (אופציונלי)
}

אינדקסים:
- alert_uid (unique, sparse)
- alert_type_name (unique, sparse)
- tags
- alert_timestamp
- compound: tags + alert_timestamp

הערות:
- Fail-open: אם DB לא זמין, נחזיר תוצאות ריקות ולא נקריס את היישום.
- Regex safety: search_tags משתמש ב-re.escape() כדי למנוע regex injection ושגיאות על תווים מיוחדים.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _is_true(val: Optional[str]) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def _enabled() -> bool:
    # Tags צריכים לעבוד כברירת מחדל, אבל נשמור על מצב CI/Docs בטוח.
    if _is_true(os.getenv("DISABLE_DB")):
        return False
    # allow explicit disable if needed (optional)
    if _is_true(os.getenv("ALERT_TAGS_DB_DISABLED")):
        return False
    return True


_client = None  # type: ignore
_collection = None  # type: ignore
_init_failed = False
_indexes_ready = False


def _get_collection():
    """מחזיר את ה-collection של alert_tags (Lazy init, fail-open)."""
    global _client, _collection, _init_failed
    if _collection is not None:
        return _collection
    if _init_failed or not _enabled():
        return None

    try:
        from pymongo import MongoClient  # type: ignore
    except Exception:
        _init_failed = True
        try:
            from observability import emit_event  # type: ignore

            emit_event("alert_tags_db_pymongo_missing", severity="warn", handled=True)
        except Exception:
            pass
        return None

    mongo_url = os.getenv("MONGODB_URL") or ""
    if not mongo_url:
        _init_failed = True
        try:
            from observability import emit_event  # type: ignore

            emit_event("alert_tags_db_missing_url", severity="warn", handled=True)
        except Exception:
            pass
        return None

    db_name = os.getenv("DATABASE_NAME") or "code_keeper_bot"
    coll_name = os.getenv("ALERT_TAGS_COLLECTION") or "alert_tags"
    try:
        _client = MongoClient(
            mongo_url,
            serverSelectionTimeoutMS=5000,
            tz_aware=True,
            tzinfo=timezone.utc,
        )
        # ping
        try:
            _client.admin.command("ping")
        except Exception:
            pass
        _collection = _client[db_name][coll_name]
        try:
            from observability import emit_event  # type: ignore

            emit_event("alert_tags_db_initialized", severity="info", handled=True)
        except Exception:
            pass
        return _collection
    except Exception as e:
        _init_failed = True
        try:
            from observability import emit_event  # type: ignore

            emit_event("alert_tags_db_init_failed", severity="warn", handled=True, error=str(e))
        except Exception:
            pass
        return None


def ensure_indexes() -> None:
    """יצירת אינדקסים נדרשים (idempotent, best-effort)."""
    global _indexes_ready
    if _indexes_ready:
        return
    coll = _get_collection()
    if coll is None:
        return
    try:
        coll.create_index("alert_uid", unique=True, sparse=True, background=True)
        coll.create_index("alert_type_name", unique=True, sparse=True, background=True)
        coll.create_index("error_signature", unique=True, sparse=True, background=True)
        coll.create_index("tags", background=True)
        coll.create_index("alert_timestamp", background=True)
        coll.create_index([("tags", 1), ("alert_timestamp", -1)], background=True)
        _indexes_ready = True
        logger.info("alert_tags indexes ensured")
    except Exception as e:
        # Fail-open
        try:
            from observability import emit_event  # type: ignore

            emit_event("alert_tags_indexes_failed", severity="warn", handled=True, error=str(e))
        except Exception:
            pass


def _normalize_tags(tags: List[str]) -> List[str]:
    # lowercase, trim, remove empties, preserve order, dedup
    # DEBUG: Log input for debugging empty tags issue
    logger.debug("🔍 _normalize_tags - input tags=%r (type=%s)", tags, type(tags).__name__)
    if tags is None:
        logger.debug("🔍 _normalize_tags - tags is None, returning []")
        return []
    if not isinstance(tags, list):
        logger.warning("🔍 _normalize_tags - tags is not a list: %s, returning []", type(tags))
        return []
    result = list(
        dict.fromkeys(
            tag.strip().lower()
            for tag in tags
            if tag and isinstance(tag, str) and tag.strip()
        )
    )
    logger.debug("🔍 _normalize_tags - output result=%r", result)
    return result


def _normalize_alert_name(value: Optional[str]) -> str:
    """
    Normalize alert name/type to a stable key for matching global tags.

    Production data isn't always consistent (e.g. "deployment-event", "Deployment Event",
    "deployment_event"). We normalize common separators into underscores so global tags
    can match reliably regardless of how the alert name arrived.
    """
    try:
        text = str(value or "").strip().lower()
    except Exception:
        return ""
    if not text:
        return ""
    # Normalize common separators to underscore
    try:
        text = re.sub(r"[\s\-./:]+", "_", text)
        text = re.sub(r"__+", "_", text).strip("_")
    except Exception:
        # Best-effort: keep the lowercased string
        text = text.strip()
    return text


def get_tags_for_alert(alert_uid: str) -> List[str]:
    """מחזיר תגיות עבור התראה ספציפית."""
    uid = str(alert_uid or "").strip()
    if not uid:
        return []
    coll = _get_collection()
    if coll is None:
        return []
    try:
        doc = coll.find_one({"alert_uid": uid})
        return list(doc.get("tags", [])) if isinstance(doc, dict) else []
    except Exception:
        return []


def get_tags_for_alerts(alert_uids: List[str]) -> Dict[str, List[str]]:
    """מחזיר מיפוי של alert_uid -> tags עבור רשימת התראות."""
    uids = [str(u or "").strip() for u in (alert_uids or []) if str(u or "").strip()]
    if not uids:
        return {}
    coll = _get_collection()
    if coll is None:
        return {}
    try:
        cursor = coll.find({"alert_uid": {"$in": uids}})
        out: Dict[str, List[str]] = {}
        for doc in cursor:
            if not isinstance(doc, dict):
                continue
            uid = str(doc.get("alert_uid") or "").strip()
            if not uid:
                continue
            out[uid] = list(doc.get("tags", []) or [])
        return out
    except Exception:
        return {}


def set_tags_for_alert(
    alert_uid: str,
    alert_timestamp: datetime,
    tags: List[str],
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """שמירת/עדכון תגיות להתראה (מחליף את הקיימות)."""
    uid = str(alert_uid or "").strip()
    if not uid:
        raise ValueError("alert_uid is required")
    normalized_tags = _normalize_tags(tags)
    now = datetime.now(timezone.utc)
    coll = _get_collection()
    if coll is None:
        # Fail-open: behave like upsert succeeded logically
        return {"alert_uid": uid, "tags": normalized_tags, "upserted": False, "modified": False}
    try:
        result = coll.update_one(
            {"alert_uid": uid},
            {
                "$set": {
                    "tags": normalized_tags,
                    "alert_timestamp": alert_timestamp,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                    "created_by": user_id,
                },
            },
            upsert=True,
        )
        upserted_id = getattr(result, "upserted_id", None)
        modified_count = getattr(result, "modified_count", 0)
        return {
            "alert_uid": uid,
            "tags": normalized_tags,
            "upserted": upserted_id is not None,
            "modified": bool(modified_count and int(modified_count) > 0),
        }
    except Exception:
        # Fail-open
        return {"alert_uid": uid, "tags": normalized_tags, "upserted": False, "modified": False}


def add_tag_to_alert(
    alert_uid: str,
    alert_timestamp: datetime,
    tag: str,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """הוספת תגית בודדת להתראה (ללא מחיקת קיימות)."""
    uid = str(alert_uid or "").strip()
    if not uid:
        raise ValueError("alert_uid is required")
    normalized = str(tag or "").strip().lower()
    if not normalized:
        raise ValueError("tag cannot be empty")
    now = datetime.now(timezone.utc)
    coll = _get_collection()
    if coll is None:
        # Fail-open
        tags = sorted(set(get_tags_for_alert(uid) + [normalized]))
        return {"alert_uid": uid, "tags": tags, "added": normalized}
    try:
        coll.update_one(
            {"alert_uid": uid},
            {
                "$addToSet": {"tags": normalized},
                "$set": {
                    "alert_timestamp": alert_timestamp,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                    "created_by": user_id,
                },
            },
            upsert=True,
        )
        updated = get_tags_for_alert(uid)
        return {"alert_uid": uid, "tags": updated, "added": normalized}
    except Exception:
        updated = get_tags_for_alert(uid)
        return {"alert_uid": uid, "tags": updated, "added": normalized}


def remove_tag_from_alert(alert_uid: str, tag: str) -> Dict[str, Any]:
    """הסרת תגית מהתראה."""
    uid = str(alert_uid or "").strip()
    if not uid:
        raise ValueError("alert_uid is required")
    normalized = str(tag or "").strip().lower()
    if not normalized:
        raise ValueError("tag is required")
    coll = _get_collection()
    if coll is None:
        updated = [t for t in get_tags_for_alert(uid) if t != normalized]
        return {"alert_uid": uid, "tags": updated, "removed": normalized, "modified": False}
    try:
        result = coll.update_one(
            {"alert_uid": uid},
            {"$pull": {"tags": normalized}, "$set": {"updated_at": datetime.now(timezone.utc)}},
        )
        modified_count = getattr(result, "modified_count", 0)
        updated = get_tags_for_alert(uid)
        return {
            "alert_uid": uid,
            "tags": updated,
            "removed": normalized,
            "modified": bool(modified_count and int(modified_count) > 0),
        }
    except Exception:
        updated = get_tags_for_alert(uid)
        return {"alert_uid": uid, "tags": updated, "removed": normalized, "modified": False}


def get_all_tags(limit: int = 100) -> List[Dict[str, Any]]:
    """מחזיר רשימת כל התגיות הקיימות עם ספירה. משמש ל-Autocomplete."""
    coll = _get_collection()
    if coll is None:
        return []
    try:
        pipeline = [
            {"$unwind": "$tags"},
            {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": int(limit or 100)},
            {"$project": {"tag": "$_id", "count": 1, "_id": 0}},
        ]
        return list(coll.aggregate(pipeline))
    except Exception:
        return []


def search_tags(prefix: str, limit: int = 20) -> List[str]:
    """
    חיפוש תגיות לפי prefix (ל-Autocomplete).

    Note: משתמש ב-re.escape() כדי למנוע injection של תווים מיוחדים
    כמו c++, tag(1), [test] וכו'.
    """
    coll = _get_collection()
    if coll is None:
        return []
    if not prefix:
        return [item.get("tag") for item in (get_all_tags(limit) or []) if item.get("tag")]
    normalized_prefix = str(prefix or "").strip().lower()
    if not normalized_prefix:
        return [item.get("tag") for item in (get_all_tags(limit) or []) if item.get("tag")]
    safe_prefix = re.escape(normalized_prefix)
    try:
        pipeline = [
            {"$unwind": "$tags"},
            {"$match": {"tags": {"$regex": f"^{safe_prefix}", "$options": "i"}}},
            {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": int(limit or 20)},
        ]
        results = list(coll.aggregate(pipeline))
        return [str(doc.get("_id")) for doc in results if doc.get("_id")]
    except Exception:
        return []


# ==========================================
# Global Tags (לפי סוג התראה)
# ==========================================


def get_tags_map_for_alerts(alerts_list: List[dict]) -> Dict[str, List[str]]:
    """
    מחזיר מפה משולבת של תגיות מכל המקורות:
    1. תגיות ספציפיות למופע (Instance) - לפי alert_uid
    2. תגיות לפי חתימת שגיאה (Signature) - לפי error_signature/sentry_issue_id
    3. תגיות גלובליות לסוג התראה (Type) - לפי alert_type

    Args:
        alerts_list: רשימת התראות.

    Returns:
        מיפוי של alert_uid -> רשימת תגיות (משולבת מכל המקורות)
    """
    if not alerts_list:
        logger.debug("get_tags_map_for_alerts: empty alerts_list")
        return {}

    # 0) איסוף UIDs + Names + Signatures עם תמיכה בשמות שדות משתנים
    uids: set[str] = set()
    names: set[str] = set()
    signatures: set[str] = set()

    # מפה עזר שתשמור לכל התראה את ה-UID, Name, וה-Signature שחילצנו ממנה
    alert_meta_map: List[Dict[str, str]] = []

    for alert in alerts_list:
        # Fallback ל-UID
        raw_uid = alert.get("alert_uid") or alert.get("uid") or alert.get("id") or alert.get("_id")
        uid = str(raw_uid or "").strip()

        # Fallback ל-Name
        raw_name = (
            alert.get("alert_type")
            or alert.get("name")
            or alert.get("alert_name")
            or alert.get("rule_name")
        )
        name = _normalize_alert_name(raw_name)

        # Extract error signature from metadata
        # Priority: sentry_issue_id > error_signature_hash
        metadata = alert.get("metadata") or {}
        raw_sig = (
            metadata.get("sentry_issue_id")
            or metadata.get("error_signature_hash")
            or ""
        )
        signature = str(raw_sig or "").strip()

        if uid:
            uids.add(uid)
            if name:
                names.add(name)
            if signature:
                signatures.add(signature)
            alert_meta_map.append({"uid": uid, "name": name, "signature": signature})

    logger.debug(
        "get_tags_map_for_alerts: collected %d uids, %d names, %d signatures",
        len(uids), len(names), len(signatures)
    )

    if not uids:
        return {}

    coll = _get_collection()
    if coll is None:
        logger.warning("get_tags_map_for_alerts: DB collection is None (fail-open)")
        return {uid: [] for uid in uids}

    # 1) שליפה של תגיות ספציפיות (Instance) לפי UID
    instance_map: Dict[str, List[str]] = {}
    try:
        cursor = coll.find(
            {"alert_uid": {"$in": list(uids)}},
            {"_id": 0, "alert_uid": 1, "tags": 1},
        )
        for doc in cursor:
            if not isinstance(doc, dict):
                continue
            uid = str(doc.get("alert_uid") or "").strip()
            if not uid:
                continue
            tags = doc.get("tags", [])
            instance_map[uid] = list(tags) if isinstance(tags, list) else []
        logger.debug("get_tags_map_for_alerts: instance_map has %d entries", len(instance_map))
    except Exception as e:
        logger.warning("get_tags_map_for_alerts: instance query failed: %s", e)
        instance_map = {}

    # 2) שליפה של תגיות לפי חתימת שגיאה (Signature)
    signature_map: Dict[str, List[str]] = {}
    if signatures:
        try:
            cursor = coll.find(
                {"error_signature": {"$in": list(signatures)}},
                {"_id": 0, "error_signature": 1, "tags": 1},
            )
            for doc in cursor:
                if not isinstance(doc, dict):
                    continue
                sig = str(doc.get("error_signature") or "").strip()
                if not sig:
                    continue
                tags = doc.get("tags", [])
                signature_map[sig] = list(tags) if isinstance(tags, list) else []
            logger.debug(
                "get_tags_map_for_alerts: signature_map has %d entries, keys=%r",
                len(signature_map), list(signature_map.keys())[:5]
            )
        except Exception as e:
            logger.warning("get_tags_map_for_alerts: signature query failed: %s", e)
            signature_map = {}

    # 3) שליפה של תגיות גלובליות (Type) לפי שם התראה
    global_map: Dict[str, List[str]] = {}
    if names:
        try:
            cursor = coll.find(
                {"alert_type_name": {"$in": list(names)}},
                {"_id": 0, "alert_type_name": 1, "tags": 1},
            )
            for doc in cursor:
                if not isinstance(doc, dict):
                    continue
                name = str(doc.get("alert_type_name") or "").strip()
                if not name:
                    continue
                tags = doc.get("tags", [])
                global_map[name] = list(tags) if isinstance(tags, list) else []
            logger.debug(
                "get_tags_map_for_alerts: global_map has %d entries, keys=%r",
                len(global_map), list(global_map.keys())[:5]
            )
        except Exception as e:
            logger.warning("get_tags_map_for_alerts: global query failed: %s", e)
            global_map = {}

    # 4) איחוד בפייתון (App-Side Merge) - סדר עדיפות:
    #    1. תגיות גלובליות (Type) - הכי כלליות
    #    2. תגיות לפי חתימה (Signature) - ספציפיות לשגיאה
    #    3. תגיות ספציפיות (Instance) - ספציפיות למופע
    final_map: Dict[str, List[str]] = {}
    for meta in alert_meta_map:
        uid = meta["uid"]
        name = meta["name"]
        signature = meta["signature"]

        merged: List[str] = []

        # תגיות גלובליות לסוג ההתראה
        if name and name in global_map:
            merged.extend([t for t in global_map.get(name, []) if isinstance(t, str) and t.strip()])

        # תגיות לפי חתימת שגיאה (מאפשר לתייג שגיאה ספציפית שחוזרת)
        if signature and signature in signature_map:
            merged.extend([t for t in signature_map.get(signature, []) if isinstance(t, str) and t.strip()])

        # תגיות ספציפיות למופע
        if uid in instance_map:
            merged.extend(
                [t for t in instance_map.get(uid, []) if isinstance(t, str) and t.strip()]
            )

        # נרמול וניקוי כפילויות
        merged_norm = _normalize_tags(merged)
        final_map[uid] = merged_norm

    # ensure missing uids are present with []
    for uid in uids:
        final_map.setdefault(uid, [])
    return final_map


def set_global_tags_for_name(
    alert_name: str,
    tags: List[str],
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """שמירת תגיות קבועות לכל ההתראות עם השם הזה.

    Note: השם מנורמל (lowercase + underscore) כדי להבטיח התאמה עקבית
    בין השמירה לשליפה, ללא תלות בפורמט המקורי של השם.
    """
    # DEBUG: Log incoming parameters
    logger.info(
        "🔍 set_global_tags_for_name ENTRY: alert_name=%r, tags=%r (type=%s, len=%s)",
        alert_name, tags, type(tags).__name__, len(tags) if isinstance(tags, list) else "N/A"
    )
    # Normalize the name for consistent matching
    name = _normalize_alert_name(alert_name)
    logger.info(
        "🔍 set_global_tags_for_name: alert_name=%r -> normalized=%r",
        alert_name, name
    )
    if not name:
        raise ValueError("alert_name is required")
    normalized_tags = _normalize_tags(tags)
    logger.info(
        "🔍 set_global_tags_for_name: normalized_tags=%r (len=%s)",
        normalized_tags, len(normalized_tags)
    )
    now = datetime.now(timezone.utc)
    coll = _get_collection()
    if coll is None:
        return {
            "alert_type_name": name,
            "tags": normalized_tags,
            "upserted": False,
            "modified": False,
        }
    try:
        result = coll.update_one(
            {"alert_type_name": name},
            {
                "$set": {
                    "tags": normalized_tags,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                    "created_by": user_id,
                },
            },
            upsert=True,
        )
        upserted_id = getattr(result, "upserted_id", None)
        modified_count = getattr(result, "modified_count", 0)
        return {
            "alert_type_name": name,
            "tags": normalized_tags,
            "upserted": upserted_id is not None,
            "modified": bool(modified_count and int(modified_count) > 0),
        }
    except Exception:
        return {
            "alert_type_name": name,
            "tags": normalized_tags,
            "upserted": False,
            "modified": False,
        }


def get_global_tags_for_name(alert_name: str) -> List[str]:
    """מחזיר תגיות גלובליות עבור סוג התראה.

    Note: השם מנורמל (lowercase + underscore) כדי להבטיח התאמה עקבית.
    """
    # Normalize for consistent lookup
    name = _normalize_alert_name(alert_name)
    if not name:
        return []
    coll = _get_collection()
    if coll is None:
        return []
    try:
        doc = coll.find_one({"alert_type_name": name})
        return list(doc.get("tags", [])) if isinstance(doc, dict) else []
    except Exception:
        return []


def remove_global_tags_for_name(alert_name: str) -> Dict[str, Any]:
    """מחיקת תגיות גלובליות לסוג התראה.

    Note: השם מנורמל (lowercase + underscore) כדי להבטיח התאמה עקבית.
    """
    # Normalize for consistent lookup
    name = _normalize_alert_name(alert_name)
    if not name:
        raise ValueError("alert_name is required")
    coll = _get_collection()
    if coll is None:
        return {"alert_type_name": name, "deleted": False}
    try:
        result = coll.delete_one({"alert_type_name": name})
        deleted_count = getattr(result, "deleted_count", 0)
        return {"alert_type_name": name, "deleted": bool(deleted_count and int(deleted_count) > 0)}
    except Exception:
        return {"alert_type_name": name, "deleted": False}


# ==========================================
# Signature Tags (לפי מזהה שגיאה ייחודי)
# ==========================================


def set_tags_for_signature(
    error_signature: str,
    tags: List[str],
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """שמירת תגיות לכל המופעים של שגיאה עם אותה חתימה.

    זה מאפשר לתייג שגיאה ספציפית (למשל Sentry issue מסוים) כך שהתגית
    תופיע בכל פעם שאותה שגיאה בדיוק חוזרת, בלי לתייג את כל סוג ההתראות.

    Args:
        error_signature: מזהה ייחודי של השגיאה (sentry_issue_id או error_signature_hash)
        tags: רשימת תגיות
        user_id: מזהה המשתמש (אופציונלי)
    """
    sig = str(error_signature or "").strip()
    logger.info(
        "🔍 set_tags_for_signature ENTRY: error_signature=%r, tags=%r (type=%s)",
        sig, tags, type(tags).__name__
    )
    if not sig:
        raise ValueError("error_signature is required")
    normalized_tags = _normalize_tags(tags)
    logger.info(
        "🔍 set_tags_for_signature: normalized_tags=%r (len=%s)",
        normalized_tags, len(normalized_tags)
    )
    now = datetime.now(timezone.utc)
    coll = _get_collection()
    if coll is None:
        return {
            "error_signature": sig,
            "tags": normalized_tags,
            "upserted": False,
            "modified": False,
        }
    try:
        result = coll.update_one(
            {"error_signature": sig},
            {
                "$set": {
                    "tags": normalized_tags,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                    "created_by": user_id,
                },
            },
            upsert=True,
        )
        upserted_id = getattr(result, "upserted_id", None)
        modified_count = getattr(result, "modified_count", 0)
        return {
            "error_signature": sig,
            "tags": normalized_tags,
            "upserted": upserted_id is not None,
            "modified": bool(modified_count and int(modified_count) > 0),
        }
    except Exception as e:
        logger.warning("set_tags_for_signature failed: %s", e)
        return {
            "error_signature": sig,
            "tags": normalized_tags,
            "upserted": False,
            "modified": False,
        }


def get_tags_for_signature(error_signature: str) -> List[str]:
    """מחזיר תגיות עבור שגיאה עם חתימה ספציפית."""
    sig = str(error_signature or "").strip()
    if not sig:
        return []
    coll = _get_collection()
    if coll is None:
        return []
    try:
        doc = coll.find_one({"error_signature": sig})
        return list(doc.get("tags", [])) if isinstance(doc, dict) else []
    except Exception:
        return []


def remove_tags_for_signature(error_signature: str) -> Dict[str, Any]:
    """מחיקת תגיות עבור שגיאה עם חתימה ספציפית."""
    sig = str(error_signature or "").strip()
    if not sig:
        raise ValueError("error_signature is required")
    coll = _get_collection()
    if coll is None:
        return {"error_signature": sig, "deleted": False}
    try:
        result = coll.delete_one({"error_signature": sig})
        deleted_count = getattr(result, "deleted_count", 0)
        return {"error_signature": sig, "deleted": bool(deleted_count and int(deleted_count) > 0)}
    except Exception:
        return {"error_signature": sig, "deleted": False}
