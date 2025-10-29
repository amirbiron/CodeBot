"""
Collections Manager – ניהול "האוספים שלי" (My Collections)

מימוש שכבת DB/Service עבור אוספים ידניים וחכמים, בהתבסס על MongoDB
והתבניות הקיימות בפרויקט (ולידציה, אינדקסים, ACL לפי user_id).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import re

try:
    from bson import ObjectId  # type: ignore
    HAS_BSON: bool = True
except Exception:  # pragma: no cover
    HAS_BSON = False
    class ObjectId(str):  # type: ignore
        pass

try:
    from pymongo import ASCENDING, DESCENDING, IndexModel  # type: ignore
except Exception:  # pragma: no cover
    ASCENDING = 1  # type: ignore
    DESCENDING = -1  # type: ignore

    class IndexModel:  # type: ignore
        def __init__(self, *args, **kwargs) -> None:
            pass

# Observability (best-effort)
try:
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields: Any) -> None:  # type: ignore
        return None

# Cache (optional; invalidate_user_cache available on write paths in API layer)
try:
    from cache_manager import cache  # type: ignore
except Exception:  # pragma: no cover
    cache = None  # type: ignore


ALLOWED_ICONS: List[str] = [
    "📂","📘","🎨","🧩","🐛","⚙️","📝","🧪","💡","⭐","🔖","🚀"
]
COLLECTION_COLORS: List[str] = [
    "blue","green","purple","orange","red","teal","pink","yellow"
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _slugify(name: str) -> str:
    """המרת שם ל-slug ידידותי ויציב: אותיות/ספרות/מקף בלבד, באורך ≤ 80."""
    s = re.sub(r"\s+", "-", str(name or "").strip())
    # השאר אותיות יוניקוד, ספרות, מקפים וקו תחתון – הסר תווים אחרים
    s = re.sub(r"[^\w\-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if not s:
        s = "collection"
    return s[:80].lower()


@dataclass
class _CollectionDoc:
    user_id: int
    name: str
    slug: str
    description: str = ""
    icon: str = ""
    color: str = ""
    is_favorite: bool = False
    sort_order: int = 0
    mode: str = "manual"  # manual|smart|mixed
    rules: Dict[str, Any] | None = None
    items_count: int = 0
    pinned_count: int = 0
    is_active: bool = True


class CollectionsManager:
    """מנהל אוספים – CRUD + אינטגרציות בסיסיות לחוקים חכמים."""

    def __init__(self, db):
        self.db = db
        self.collections = db.user_collections
        self.items = db.collection_items
        self.code_snippets = getattr(db, "code_snippets", None)
        self._ensure_indexes()

    # --- Indexes ---
    def _ensure_indexes(self) -> None:
        try:
            self.collections.create_indexes([
                IndexModel([("user_id", ASCENDING), ("slug", ASCENDING)], name="user_slug_unique", unique=True),
                IndexModel([("user_id", ASCENDING), ("is_active", ASCENDING), ("updated_at", DESCENDING)], name="user_active_updated"),
                IndexModel([("user_id", ASCENDING), ("sort_order", ASCENDING)], name="user_sort_order"),
            ])
        except Exception:
            pass
        try:
            self.items.create_indexes([
                IndexModel([("collection_id", ASCENDING), ("source", ASCENDING), ("file_name", ASCENDING)], name="unique_item", unique=True),
                IndexModel([("collection_id", ASCENDING), ("custom_order", ASCENDING), ("pinned", DESCENDING)], name="order_pin"),
                IndexModel([("user_id", ASCENDING)], name="by_user"),
            ])
        except Exception:
            pass

    # --- Validators ---
    def _validate_name(self, name: str) -> bool:
        return isinstance(name, str) and 1 <= len(name.strip()) <= 80

    def _validate_description(self, description: str) -> bool:
        return isinstance(description, str) and len(description) <= 500

    def _validate_mode(self, mode: str) -> bool:
        return str(mode or "manual").lower() in {"manual", "smart", "mixed"}

    def _normalize_icon(self, icon: Optional[str]) -> str:
        return icon if (icon in ALLOWED_ICONS) else ""

    def _normalize_color(self, color: Optional[str]) -> str:
        c = str(color or "").lower()
        return c if c in COLLECTION_COLORS else ""

    # --- Collections CRUD ---
    def create_collection(
        self,
        user_id: int,
        name: str,
        description: str = "",
        mode: str = "manual",
        rules: Optional[Dict[str, Any]] = None,
        *,
        icon: Optional[str] = None,
        color: Optional[str] = None,
        is_favorite: Optional[bool] = None,
        sort_order: Optional[int] = None,
    ) -> Dict[str, Any]:
        # מגבלה: עד 100 אוספים למשתמש
        try:
            total = int(self.collections.count_documents({"user_id": int(user_id), "$or": [{"is_active": True}, {"is_active": {"$exists": False}}]}))
            if total >= 100:
                # דרישה: להחזיר הודעה אחידה באנגלית וללא שדה collection
                return {"ok": False, "error": "user has reached limit 100"}
        except Exception:
            pass
        if not self._validate_name(name):
            return {"ok": False, "error": "שם האוסף חייב להיות 1..80 תווים"}
        if not self._validate_description(description or ""):
            return {"ok": False, "error": "תיאור עד 500 תווים"}
        if not self._validate_mode(mode):
            return {"ok": False, "error": "מצב לא תקין"}
        base_slug = _slugify(name)
        slug = base_slug
        # הבטח ייחודיות slug למשתמש – הוסף סיומת מספרית אם נדרש
        try:
            i = 1
            while self.collections.find_one({"user_id": user_id, "slug": slug}):
                i += 1
                slug = f"{base_slug}-{i}"
        except Exception:
            pass

        doc: Dict[str, Any] = {
            "user_id": int(user_id),
            "name": name.strip(),
            "slug": slug,
            "description": (description or "")[:500],
            "icon": self._normalize_icon(icon),
            "color": self._normalize_color(color),
            "is_favorite": bool(is_favorite) if is_favorite is not None else False,
            "sort_order": int(sort_order) if isinstance(sort_order, int) else 0,
            "mode": str(mode or "manual").lower(),
            "rules": dict(rules or {}),
            "items_count": 0,
            "pinned_count": 0,
            "is_active": True,
            "created_at": _now(),
            "updated_at": _now(),
        }
        # מזהה: בפרודקשן נשמור _id כ-ObjectId אמיתי, אך נחזיר/נייצג id כמחרוזת זהה
        if HAS_BSON:
            oid = ObjectId()
            doc["_id"] = oid
            doc["id"] = str(oid)
        else:
            # ללא bson: שמור מזהה hex באורך 24 גם ב-_id וגם ב-id
            import os, binascii
            _generated_id = binascii.hexlify(os.urandom(12)).decode()
            doc["_id"] = _generated_id
            doc["id"] = _generated_id
        try:
            self.collections.insert_one(doc)
            emit_event("collections_create", user_id=int(user_id), collection_id=str(doc.get("_id")))
            return {"ok": True, "collection": self._public_collection(doc)}
        except Exception as e:
            emit_event("collections_create_error", severity="error", user_id=int(user_id), error=str(e))
            return {"ok": False, "error": "שגיאה ביצירת האוסף"}

    def update_collection(self, user_id: int, collection_id: str, **fields: Any) -> Dict[str, Any]:
        try:
            cid = ObjectId(collection_id)
        except Exception:
            return {"ok": False, "error": "collection_id לא תקין"}

        updates: Dict[str, Any] = {}
        if "name" in fields:
            name = str(fields.get("name") or "").strip()
            if not self._validate_name(name):
                return {"ok": False, "error": "שם לא תקין"}
            updates["name"] = name
            # עדכן גם slug באופן דטרמיניסטי (שמור ייחודיות)
            base_slug = _slugify(name)
            slug = base_slug
            try:
                i = 1
                while self.collections.find_one({
                    "_id": {"$ne": cid}, "user_id": user_id, "slug": slug
                }):
                    i += 1
                    slug = f"{base_slug}-{i}"
            except Exception:
                pass
            updates["slug"] = slug
        if "description" in fields:
            desc = str(fields.get("description") or "")
            if not self._validate_description(desc):
                return {"ok": False, "error": "תיאור ארוך מדי"}
            updates["description"] = desc
        if "icon" in fields:
            updates["icon"] = self._normalize_icon(fields.get("icon"))
        if "color" in fields:
            updates["color"] = self._normalize_color(fields.get("color"))
        if "is_favorite" in fields:
            updates["is_favorite"] = bool(fields.get("is_favorite"))
        if "sort_order" in fields and isinstance(fields.get("sort_order"), int):
            updates["sort_order"] = int(fields.get("sort_order"))
        if "mode" in fields:
            mode = str(fields.get("mode") or "manual").lower()
            if not self._validate_mode(mode):
                return {"ok": False, "error": "מצב לא תקין"}
            updates["mode"] = mode
        if "rules" in fields and isinstance(fields.get("rules"), dict):
            updates["rules"] = dict(fields.get("rules") or {})

        if not updates:
            return {"ok": False, "error": "אין שדות לעדכון"}
        updates["updated_at"] = _now()

        try:
            res = self.collections.find_one_and_update(
                {"_id": cid, "user_id": user_id, "$or": [{"is_active": True}, {"is_active": {"$exists": False}}]},
                {"$set": updates},
                return_document=True,
            )
            if not res:
                return {"ok": False, "error": "האוסף לא נמצא"}
            emit_event("collections_update", user_id=int(user_id), collection_id=str(collection_id))
            return {"ok": True, "collection": self._public_collection(res)}
        except Exception as e:
            emit_event("collections_update_error", severity="error", user_id=int(user_id), error=str(e))
            return {"ok": False, "error": "שגיאה בעדכון האוסף"}

    def delete_collection(self, user_id: int, collection_id: str) -> Dict[str, Any]:
        try:
            cid = ObjectId(collection_id)
        except Exception:
            return {"ok": False, "error": "collection_id לא תקין"}
        try:
            res = self.collections.update_one(
                {"_id": cid, "user_id": user_id, "$or": [{"is_active": True}, {"is_active": {"$exists": False}}]},
                {"$set": {"is_active": False, "updated_at": _now()}},
            )
            if getattr(res, "modified_count", 0) > 0:
                emit_event("collections_delete_soft", user_id=int(user_id), collection_id=str(collection_id))
                return {"ok": True}
            return {"ok": False, "error": "האוסף לא נמצא"}
        except Exception as e:
            emit_event("collections_delete_error", severity="error", user_id=int(user_id), error=str(e))
            return {"ok": False, "error": "שגיאה במחיקת האוסף"}

    def list_collections(self, user_id: int, limit: int = 100, skip: int = 0) -> Dict[str, Any]:
        try:
            eff_limit = max(1, min(int(limit or 100), 500))
            eff_skip = max(0, int(skip or 0))
        except Exception:
            eff_limit, eff_skip = 100, 0

        flt = {"user_id": user_id, "$or": [{"is_active": True}, {"is_active": {"$exists": False}}]}

        try:
            found = self.collections.find(flt)

            # כאשר find מחזיר רשימה (בסביבת טסט/דמה) – בצע מיון/דפדוף בפייתון
            if isinstance(found, list):
                def _sort_key(d: Dict[str, Any]):
                    is_fav_rank = 0 if bool(d.get("is_favorite")) else 1  # מועדפים תחילה
                    sort_order = int(d.get("sort_order") or 0)
                    upd = d.get("updated_at")
                    try:
                        # סדר יורד – שלילי של timestamp
                        upd_ts = -float(upd.timestamp()) if hasattr(upd, "timestamp") else 0.0
                    except Exception:
                        upd_ts = 0.0
                    return (is_fav_rank, sort_order, upd_ts)

                rows = list(found)
                rows.sort(key=_sort_key)
                rows = rows[eff_skip: eff_skip + eff_limit]
            else:
                # PyMongo cursor – ניתן להשתמש ב-sort/skip/limit של הנהג
                cur = found.sort([
                    ("is_favorite", -1), ("sort_order", 1), ("updated_at", -1)
                ]).skip(eff_skip).limit(eff_limit)
                rows = list(cur)

            total = int(self.collections.count_documents(flt))
            return {
                "ok": True,
                "collections": [self._public_collection(d) for d in rows],
                "count": total,
            }
        except Exception as e:
            emit_event("collections_get_list_error", severity="error", user_id=int(user_id), error=str(e))
            return {"ok": False, "collections": [], "count": 0}

    def get_collection(self, user_id: int, collection_id: str) -> Dict[str, Any]:
        try:
            cid = ObjectId(collection_id)
        except Exception:
            return {"ok": False, "error": "collection_id לא תקין"}
        try:
            doc = self.collections.find_one(
                {"_id": cid, "user_id": user_id}
            )
            if not doc:
                return {"ok": False, "error": "האוסף לא נמצא"}
            return {"ok": True, "collection": self._public_collection(doc)}
        except Exception as e:
            emit_event("collections_get_detail_error", severity="error", user_id=int(user_id), error=str(e))
            return {"ok": False, "error": "שגיאה בשליפת האוסף"}

    # --- Items operations ---
    def add_items(self, user_id: int, collection_id: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            cid = ObjectId(collection_id)
        except Exception:
            return {"ok": False, "error": "collection_id לא תקין"}
        if not isinstance(items, list) or not items:
            return {"ok": False, "error": "items חסר"}
        # מגבלה: עד 5000 פריטים ידניים למשתמש בכלל האוספים
        try:
            current_total = int(self.items.count_documents({"user_id": int(user_id)}))
            if current_total >= 5000:
                return {"ok": False, "error": "חרגת מהמגבלה: עד 5000 פריטים ידניים למשתמש"}
        except Exception:
            pass
        added_count = 0
        updated_count = 0
        now = _now()
        for it in items:
            try:
                source = str((it.get("source") or "regular")).lower()
                if source not in {"regular", "large"}:
                    source = "regular"
                file_name = str(it.get("file_name") or "").strip()
                if not file_name:
                    continue

                # נסה קודם לעדכן פריט קיים; אם לא קיים – נכניס חדש
                query = {
                    "collection_id": cid,
                    "user_id": int(user_id),
                    "source": source,
                    "file_name": file_name,
                }

                set_fields: Dict[str, Any] = {"updated_at": now}
                if "note" in it:
                    set_fields["note"] = str(it.get("note") or "")[:500]
                if "pinned" in it:
                    set_fields["pinned"] = bool(it.get("pinned"))
                if "custom_order" in it:
                    set_fields["custom_order"] = it.get("custom_order")

                try:
                    upd_res = self.items.update_one(query, {"$set": set_fields})
                    matched = int(getattr(upd_res, "matched_count", 0) or 0)
                except Exception:
                    matched = 0

                if matched > 0:
                    updated_count += 1
                    continue

                # אם לא עודכן כלום – הוסף כחדש
                doc = {
                    "collection_id": cid,
                    "user_id": int(user_id),
                    "source": source,
                    "file_name": file_name,
                    "note": str(it.get("note") or "")[:500],
                    "pinned": bool(it.get("pinned") or False),
                    "custom_order": it.get("custom_order"),
                    "added_at": now,
                    "updated_at": now,
                }
                try:
                    self.items.insert_one(doc)
                    added_count += 1
                except Exception:
                    # במידה והכנסה נכשלה (למשל כפילות נדירה) – נסה עדכון אחרון
                    try:
                        self.items.update_one(query, {"$set": set_fields})
                        updated_count += 1
                    except Exception:
                        # התעלם מפריט בעייתי כדי לא לחסום אחרים
                        continue
            except Exception:
                continue
        # עדכון מונים באוסף — תחום למשתמש ולאוסף כדי למנוע פגיעה צולבת
        try:
            agg = list(self.items.aggregate([
                {"$match": {"collection_id": cid, "user_id": int(user_id)}},
                {"$group": {"_id": None, "cnt": {"$sum": 1}, "pinned": {"$sum": {"$cond": ["$pinned", 1, 0]}}}},
            ]))
            items_count = int((agg[0].get("cnt") if agg else 0) or 0)
            pinned_count = int((agg[0].get("pinned") if agg else 0) or 0)
            self.collections.update_one({"_id": cid, "user_id": int(user_id)}, {"$set": {"items_count": items_count, "pinned_count": pinned_count, "updated_at": _now()}})
        except Exception:
            pass
        emit_event("collections_items_add", user_id=int(user_id), collection_id=str(collection_id), count=int(added_count))
        return {"ok": True, "added": int(added_count), "updated": int(updated_count)}

    def remove_items(self, user_id: int, collection_id: str, items: List[Dict[str, Any]]) -> Dict[str, Any]:
        try:
            cid = ObjectId(collection_id)
        except Exception:
            return {"ok": False, "error": "collection_id לא תקין"}
        if not isinstance(items, list) or not items:
            return {"ok": False, "error": "items חסר"}
        deleted = 0
        for it in items:
            try:
                source = str((it.get("source") or "regular")).lower()
                if source not in {"regular", "large"}:
                    source = "regular"
                file_name = str(it.get("file_name") or "").strip()
                if not file_name:
                    continue
                res = self.items.delete_one({"collection_id": cid, "user_id": user_id, "source": source, "file_name": file_name})
                deleted += int(getattr(res, "deleted_count", 0) or 0)
            except Exception:
                continue
        # עדכון מונים — תחום למשתמש
        try:
            agg = list(self.items.aggregate([
                {"$match": {"collection_id": cid, "user_id": int(user_id)}},
                {"$group": {"_id": None, "cnt": {"$sum": 1}, "pinned": {"$sum": {"$cond": ["$pinned", 1, 0]}}}},
            ]))
            items_count = int((agg[0].get("cnt") if agg else 0) or 0)
            pinned_count = int((agg[0].get("pinned") if agg else 0) or 0)
            self.collections.update_one({"_id": cid, "user_id": int(user_id)}, {"$set": {"items_count": items_count, "pinned_count": pinned_count, "updated_at": _now()}})
        except Exception:
            pass
        emit_event("collections_items_remove", user_id=int(user_id), collection_id=str(collection_id), count=int(deleted))
        return {"ok": True, "deleted": deleted}

    def reorder_items(self, user_id: int, collection_id: str, order: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Reorder items within a collection.

        Requirements (for FakeDB compatibility and simplicity):
        - Do not use update_many/bulk.
        - Load the collection document, update its "items" field to reflect
          the new order (list of {source, file_name}), update items_count,
          and return updated=len(new_items) and the items list.
        - Continue to set per-item custom_order in the items store so that
          existing sorting logic remains correct.
        """
        try:
            cid = ObjectId(collection_id)
        except Exception:
            return {"ok": False, "error": "collection_id לא תקין"}

        if not isinstance(order, list) or not order:
            return {"ok": False, "error": "order חסר"}

        # Normalize requested order into a clean list of items
        new_items: List[Dict[str, Any]] = []
        for it in order:
            try:
                source = str((it.get("source") or "regular")).lower()
                if source not in {"regular", "large"}:
                    source = "regular"
                file_name = str(it.get("file_name") or "").strip()
                if not file_name:
                    continue
                new_items.append({"source": source, "file_name": file_name})
            except Exception:
                continue

        # Apply custom_order per item (pos starts at 1) without bulk
        pos = 1
        had_update_error = False
        first_error_message: Optional[str] = None
        for it in new_items:
            try:
                res = self.items.update_one(
                    {"collection_id": cid, "user_id": user_id, "source": it["source"], "file_name": it["file_name"]},
                    {"$set": {"custom_order": pos, "updated_at": _now()}},
                )
                # advance position only if an item was actually matched/updated
                # תמיכה גם במימושי Fake/Stub שמדווחים modified_count אך לא matched_count
                matched = int(getattr(res, "matched_count", 0) or 0)
                if matched <= 0:
                    matched = int(getattr(res, "modified_count", 0) or 0)
                if matched > 0:
                    pos += 1
            except Exception as e:
                # Do not raise – mark error and continue as per requirement
                had_update_error = True
                if first_error_message is None:
                    first_error_message = str(e)
                continue

        # Load and update the collection document's items and items_count
        try:
            col = self.collections.find_one({
                "_id": cid,
                "user_id": int(user_id),
                "$or": [{"is_active": True}, {"is_active": {"$exists": False}}],
            })
            if not col:
                return {"ok": False, "error": "האוסף לא נמצא"}

            self.collections.update_one(
                {"_id": cid, "user_id": int(user_id)},
                {"$set": {"items": new_items, "items_count": len(new_items), "updated_at": _now()}},
            )
        except Exception:
            # Best-effort: even if updating the collection doc fails, do not crash
            pass

        # If any per-item update failed, log error and report updated=0
        if had_update_error:
            emit_event(
                "collections_reorder_error",
                severity="error",
                user_id=int(user_id),
                collection_id=str(collection_id),
                count=int(len(new_items)),
                error=str(first_error_message or "update_one failed"),
                handled=True,
            )
            # Report how many actually succeeded: pos starts at 1 and
            # increments only on successful matched updates
            updated_count = max(0, int(pos - 1))
        else:
            updated_count = len(new_items)

        emit_event("collections_reorder", user_id=int(user_id), collection_id=str(collection_id), count=int(updated_count))
        return {"ok": True, "updated": updated_count, "items": new_items}

    def get_collection_items(
        self,
        user_id: int,
        collection_id: str,
        *,
        page: int = 1,
        per_page: int = 20,
        include_computed: bool = True,
    ) -> Dict[str, Any]:
        try:
            cid = ObjectId(collection_id)
        except Exception:
            return {"ok": False, "error": "collection_id לא תקין"}
        try:
            # שליפת אוסף לקבלת המוד והחוקים
            col = self.collections.find_one({"_id": cid, "user_id": user_id})
            if not col:
                return {"ok": False, "error": "האוסף לא נמצא"}
            mode = str(col.get("mode") or "manual").lower()
            rules = dict(col.get("rules") or {})

            # פריטים ידניים
            manual_cur = self.items.find({"collection_id": cid, "user_id": user_id})
            manual_list: List[Dict[str, Any]] = list(manual_cur) if not isinstance(manual_cur, list) else manual_cur
            manual_total = len(manual_list)

            # פריטים חכמים (ע"פ חוקים)
            computed: List[Dict[str, Any]] = []
            if include_computed and mode in {"smart", "mixed"}:
                computed = self.compute_smart_items(user_id, rules, limit=200)
            comp_total = len(computed)

            out_items: List[Dict[str, Any]] = []
            if mode == "manual":
                out_items = manual_list
            elif mode == "smart":
                out_items = computed
            else:  # mixed
                seen: set[Tuple[str, str]] = set()
                # שמור סדר: pinned > custom_order > updated_at > file_name
                for m in manual_list:
                    key = (str(m.get("source") or "regular"), str(m.get("file_name") or ""))
                    if key in seen:
                        continue
                    seen.add(key)
                    out_items.append(m)
                for c in computed:
                    key = (str(c.get("source") or "regular"), str(c.get("file_name") or ""))
                    if key in seen:
                        continue
                    seen.add(key)
                    out_items.append(c)

            # מיון בסיסי
            def _sort_key(d: Dict[str, Any]):
                # ודא שסדר מותאם אישית יילקח גם אם נשמר כמחרוזת ספרתית (למשל ע"י FakeDB)
                co_raw = d.get("custom_order")
                try:
                    # המרה בטוחה ל-int; אם אין ערך/לא מספרי — קבע ערך גדול כדי שימוין לאחרים
                    co_val = int(co_raw)
                except Exception:
                    co_val = 1_000_000
                return (
                    0 if bool(d.get("pinned")) else 1,
                    co_val,
                    str(d.get("file_name") or "").lower(),
                )

            out_items.sort(key=_sort_key)

            # דפדוף
            try:
                p = max(1, int(page or 1))
                pp = max(1, min(200, int(per_page or 20)))
            except Exception:
                p, pp = 1, 20
            start = (p - 1) * pp
            end = start + pp
            page_items = out_items[start:end]

            # החזרה
            return {
                "ok": True,
                "items": [self._public_item(x) for x in page_items],
                "page": p,
                "per_page": pp,
                "total_manual": manual_total,
                "total_computed": comp_total,
            }
        except Exception as e:
            emit_event("collections_get_items_error", severity="error", user_id=int(user_id), error=str(e))
            return {"ok": False, "error": "שגיאה בשליפת פריטים"}

    def compute_smart_items(self, user_id: int, rules: Dict[str, Any], limit: int = 200) -> List[Dict[str, Any]]:
        """הפקת פריטים על בסיס חוקים פשוטים מתוך אוסף code_snippets.

        כל פריט מוחזר בפורמט: {source: "regular", file_name: str}
        """
        if self.code_snippets is None:
            return []
        try:
            flt: Dict[str, Any] = {"user_id": int(user_id), "$or": [{"is_active": True}, {"is_active": {"$exists": False}}]}
            q = str(rules.get("query") or "").strip()
            if q:
                flt["$text"] = {"$search": q}
            lang = str(rules.get("programming_language") or "").strip()
            if lang:
                flt["programming_language"] = lang
            tags = rules.get("tags")
            if isinstance(tags, list) and tags:
                flt["tags"] = {"$in": [str(t) for t in tags if isinstance(t, str) and t]}
            repo_tag = str(rules.get("repo_tag") or "").strip()
            if repo_tag:
                flt.setdefault("tags", {})
                # אם כבר יש $in, ודא שהתנאי כולל גם repo_tag; אחרת קבע חיתוך פשוט
                if isinstance(flt["tags"], dict) and "$in" in flt["tags"]:
                    arr = list(flt["tags"]["$in"])
                    if repo_tag not in arr:
                        arr.append(repo_tag)
                    flt["tags"]["$in"] = arr
                else:
                    flt["tags"] = repo_tag

            pipeline = [
                {"$match": flt},
                {"$sort": {"file_name": 1, "version": -1}},
                {"$group": {"_id": "$file_name", "latest": {"$first": "$$ROOT"}}},
                {"$replaceRoot": {"newRoot": "$latest"}},
                {"$sort": {"updated_at": -1}},
                {"$project": {"_id": 0, "file_name": 1}},
                {"$limit": max(1, int(limit or 200))},
            ]
            rows = list(self.code_snippets.aggregate(pipeline, allowDiskUse=True))
            out: List[Dict[str, Any]] = []
            for r in rows:
                fn = r.get("file_name")
                if fn:
                    out.append({"source": "regular", "file_name": fn})
            return out
        except Exception:
            return []

    # --- Public mappers ---
    def _public_collection(self, d: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(d.get("_id")) if d.get("_id") is not None else None,
            "user_id": d.get("user_id"),
            "name": d.get("name"),
            "slug": d.get("slug"),
            "description": d.get("description") or "",
            "icon": d.get("icon") or "",
            "color": d.get("color") or "",
            "is_favorite": bool(d.get("is_favorite", False)),
            "sort_order": int(d.get("sort_order") or 0),
            "mode": d.get("mode") or "manual",
            "rules": d.get("rules") or {},
            "items_count": int(d.get("items_count") or 0),
            "pinned_count": int(d.get("pinned_count") or 0),
            "is_active": bool(d.get("is_active", True)),
            "created_at": (d.get("created_at").isoformat() if isinstance(d.get("created_at"), datetime) else None),
            "updated_at": (d.get("updated_at").isoformat() if isinstance(d.get("updated_at"), datetime) else None),
            "share": d.get("share") or {"enabled": False, "token": None, "visibility": "private"},
        }

    def _public_item(self, d: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(d.get("_id")) if d.get("_id") is not None else None,
            "collection_id": (str(d.get("collection_id")) if d.get("collection_id") is not None else None),
            "user_id": int(d.get("user_id") or 0),
            "source": str(d.get("source") or "regular"),
            "file_name": d.get("file_name"),
            "note": d.get("note") or "",
            "pinned": bool(d.get("pinned", False)),
            "custom_order": d.get("custom_order"),
            "added_at": (d.get("added_at").isoformat() if isinstance(d.get("added_at"), datetime) else None),
            "updated_at": (d.get("updated_at").isoformat() if isinstance(d.get("updated_at"), datetime) else None),
        }
