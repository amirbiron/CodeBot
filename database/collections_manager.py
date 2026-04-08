"""
Collections Manager – ניהול "האוספים שלי" (My Collections)

מימוש שכבת DB/Service עבור אוספים ידניים וחכמים, בהתבסס על MongoDB
והתבניות הקיימות בפרויקט (ולידציה, אינדקסים, ACL לפי user_id).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import logging
import os
import re
import time

try:
    from bson import ObjectId  # type: ignore
    HAS_BSON: bool = True
except Exception:  # pragma: no cover
    HAS_BSON = False
    _OID_RE = re.compile(r"^[0-9a-fA-F]{24}$")

    class ObjectId(str):  # type: ignore
        """Fallback ObjectId validator for environments without bson.

        We validate the canonical 24-hex string format so that code paths that
        expect bson.ObjectId behavior (e.g. rejecting invalid ids) keep working
        גם בסביבת טסטים/CI ללא bson.
        """

        def __new__(cls, value: Any) -> "ObjectId":  # type: ignore[override]
            s = str(value or "").strip()
            if not _OID_RE.match(s):
                raise ValueError("Invalid ObjectId")
            return str.__new__(cls, s)  # type: ignore[arg-type]

try:
    from pymongo import ASCENDING, DESCENDING, IndexModel  # type: ignore
    from pymongo.errors import DuplicateKeyError  # type: ignore
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

logger = logging.getLogger(__name__)


ALLOWED_ICONS: List[str] = [
    "📂","📘","🎨","🧩","🐛","⚙️","📝","🧪","💡","⭐","🔖","🚀",
    "🖥️","💼","🖱️","⌨️","📱","💻","🖨️","📊","📈","📉","🔧","🛠️",
    "🛒","📦","⚡","📢","🤖","💬","📨","🔔","🧰","🎵","🎥","📤","📥","📜","🪄"
]
COLLECTION_COLORS: List[str] = [
    "blue","green","purple","orange","red","teal","pink","yellow"
]

# תגיות מותרות (whitelist)
ALLOWED_TAGS: List[str] = [
    # עדיפות
    "🐢",  # לא דחוף
    "🔥",  # דחוף

    # סנטימנט
    "🔮",  # קסום
    "♥️",  # מועדף
    "💎",  # איכותי

    # אבטחה
    "🔐",  # סודי

    # סטטוס
    "💭",  # רעיון
    "⏸️",  # מושהה
    "🎯",  # מטרה

    # קטגוריה
    "🐛",  # באג
    "🗄️",  # דאטה-בייס
    "🧪",  # ניסיוני

    # סדר
    "1️⃣",  # ראשון
    "2️⃣",  # שני
    "3️⃣",  # שלישי
]

# קטגוריות תגיות
TAG_CATEGORIES: Dict[str, List[str]] = {
    "priority": ["🐢", "🔥"],
    "sentiment": ["🔮", "♥️", "💎"],
    "security": ["🔐"],
    "status": ["💭", "⏸️", "🎯"],
    "category": ["🐛", "🗄️", "🧪"],
    "order": ["1️⃣", "2️⃣", "3️⃣"],
}

# מטאדאטה לכל תגית
TAG_METADATA: Dict[str, Dict[str, str]] = {
    "🐢": {"name_he": "לא דחוף", "name_en": "low priority", "category": "priority"},
    "🔥": {"name_he": "דחוף", "name_en": "urgent", "category": "priority"},
    "🔮": {"name_he": "קסום", "name_en": "magic", "category": "sentiment"},
    "♥️": {"name_he": "מועדף", "name_en": "favorite", "category": "sentiment"},
    "💎": {"name_he": "איכותי", "name_en": "quality", "category": "sentiment"},
    "🔐": {"name_he": "סודי", "name_en": "secret", "category": "security"},
    "💭": {"name_he": "רעיון", "name_en": "idea", "category": "status"},
    "⏸️": {"name_he": "מושהה", "name_en": "paused", "category": "status"},
    "🎯": {"name_he": "מטרה", "name_en": "goal", "category": "status"},
    "🐛": {"name_he": "באג", "name_en": "bug", "category": "category"},
    "🗄️": {"name_he": "דאטה-בייס", "name_en": "database", "category": "category"},
    "🧪": {"name_he": "ניסיוני", "name_en": "experimental", "category": "category"},
    "1️⃣": {"name_he": "ראשון", "name_en": "first", "category": "order"},
    "2️⃣": {"name_he": "שני", "name_en": "second", "category": "order"},
    "3️⃣": {"name_he": "שלישי", "name_en": "third", "category": "order"},
}

# מגבלות
MAX_TAGS_PER_ITEM = 10  # מקסימום תגיות לפריט
MAX_FOLDERS_PER_COLLECTION = 20  # מקסימום תיקיות לאוסף
FOLDER_NAME_MAX_LEN = 60  # אורך מקסימלי לשם תיקיה
ALLOWED_FOLDER_ICONS: List[str] = [
    "📁", "📂", "📘", "🎨", "🧩", "🐛", "⚙️", "📝", "🧪", "💡",
    "⭐", "🔖", "🚀", "🖥️", "💼", "📦", "⚡", "🤖", "🧰", "📜",
]
RESERVED_FOLDER_NAMES: set = {"reorder"}
WORKSPACE_STATES: Tuple[str, ...] = ("todo", "in_progress", "done")
DEFAULT_WORKSPACE_STATE: str = WORKSPACE_STATES[0]


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
        # תמיכה בקבצים גדולים (large_files) לצורך בדיקת סטטוס פעילות
        try:
            self.large_files = getattr(db, "large_files", None)
        except Exception:
            self.large_files = None
        # תיעוד פעילות צפייה/הורדה בשיתופים
        try:
            self.share_activity = getattr(db, "collection_share_activity", None)
        except Exception:
            self.share_activity = None
        self._ensure_indexes()

    # --- Indexes ---
    def _ensure_indexes(self) -> None:
        try:
            self.collections.create_indexes([
                IndexModel([("user_id", ASCENDING), ("slug", ASCENDING)], name="user_slug_unique", unique=True),
                IndexModel([("user_id", ASCENDING), ("is_active", ASCENDING), ("updated_at", DESCENDING)], name="user_active_updated"),
                # חיפוש מהיר לפי שם (למשל "שולחן עבודה") תחת user_id + is_active
                IndexModel([("user_id", ASCENDING), ("is_active", ASCENDING), ("name", ASCENDING)], name="user_active_name"),
                IndexModel([("user_id", ASCENDING), ("sort_order", ASCENDING)], name="user_sort_order"),
            ])
        except Exception:
            pass
        try:
            self.items.create_indexes([
                IndexModel([("collection_id", ASCENDING), ("source", ASCENDING), ("file_name", ASCENDING), ("folder", ASCENDING)], name="unique_item_folder", unique=True),
                IndexModel([("collection_id", ASCENDING), ("custom_order", ASCENDING), ("pinned", DESCENDING)], name="order_pin"),
                IndexModel([("user_id", ASCENDING)], name="by_user"),
                IndexModel([("collection_id", ASCENDING), ("tags", ASCENDING)], name="collection_tags"),
                IndexModel([("collection_id", ASCENDING), ("folder", ASCENDING)], name="collection_folder"),
            ])
        except Exception:
            pass
        # מיגרציה: הסרת אינדקס ישן (ללא folder) אם קיים
        try:
            self.items.drop_index("unique_item")
        except Exception:
            pass
        # מיגרציה: backfill — פריטים קיימים ללא folder יקבלו "" (root)
        # ב-MongoDB, שדה חסר מאונדקס כ-null שזה שונה מ-"", אז חייבים לעדכן
        try:
            self.items.update_many(
                {"$or": [{"folder": None}, {"folder": {"$exists": False}}]},
                {"$set": {"folder": ""}},
            )
        except Exception:
            pass

    def ensure_default_collections(self, user_id: int) -> bool:
        """מאבטח יצירה של אוספים מובנים עבור משתמש חדש.

        מחזיר True אם נוצר אוסף חדש (למשל "שולחן עבודה"), אחרת False.
        """
        try:
            uid = int(user_id)
        except Exception:
            return False

        try:
            existing = self.collections.find_one({
                "user_id": uid,
                "name": "שולחן עבודה",
            })
        except Exception:
            existing = None

        if existing:
            return False

        created = False
        try:
            result = self.create_collection(
                user_id=uid,
                name="שולחן עבודה",
                description="קבצים שאני עובד עליהם כרגע",
                mode="manual",
                icon="🖥️",
                color="purple",
                is_favorite=True,
                sort_order=-1,
            )
            created = bool(result.get("ok")) if isinstance(result, dict) else False
        except Exception:
            created = False

        if created:
            try:
                cache.delete_pattern(f"collections_list:{uid}:*")
                cache.delete_pattern(f"collections_list:v2:{uid}:*")
                cache.delete_pattern(f"collections_detail:{uid}:*")
                cache.delete_pattern(f"collections_items:{uid}:*")
            except Exception:
                pass

        return created

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

    def _validate_tags(self, tags: Any) -> Tuple[bool, Optional[str]]:
        """
        מוודא שרשימת התגיות תקינה.

        Args:
            tags: רשימת תגיות (אימוג'ים)

        Returns:
            tuple: (is_valid, error_message)
        """
        if tags is None:
            return True, None

        if not isinstance(tags, list):
            return False, "tags must be a list"

        if len(tags) > MAX_TAGS_PER_ITEM:
            return False, f"maximum {MAX_TAGS_PER_ITEM} tags allowed per item"

        for tag in tags:
            if not isinstance(tag, str):
                return False, "tags must be strings"

        # בדיקת uniqueness
        if len(tags) != len(set(tags)):
            return False, "duplicate tags not allowed"

        # בדיקת whitelist
        for tag in tags:
            if tag not in ALLOWED_TAGS:
                return False, f"invalid tag: {tag}"

        return True, None

    def _validate_folder_name(self, name: Any) -> Tuple[bool, Optional[str]]:
        """ולידציית שם תיקיה."""
        if name is None or name == "":
            return True, None  # ריק = root
        if not isinstance(name, str):
            return False, "folder name must be a string"
        name = name.strip()
        if len(name) < 1 or len(name) > FOLDER_NAME_MAX_LEN:
            return False, f"folder name must be 1..{FOLDER_NAME_MAX_LEN} characters"
        if name.lower() in RESERVED_FOLDER_NAMES:
            return False, "שם תיקיה שמור ולא ניתן לשימוש"
        return True, None

    def _normalize_folder(self, folder: Any) -> str:
        """נרמול שדה folder: ריק/None => '' (root)."""
        if folder is None:
            return ""
        try:
            return str(folder).strip()[:FOLDER_NAME_MAX_LEN]
        except Exception:
            return ""

    def _normalize_folder_icon(self, icon: Optional[str]) -> str:
        return icon if (icon in ALLOWED_FOLDER_ICONS) else "📁"

    def _normalize_workspace_state(self, state: Optional[str], *, allow_default: bool = True) -> str:
        try:
            value = str(state or "").strip().lower()
        except Exception:
            value = ""
        if value in WORKSPACE_STATES:
            return value
        return DEFAULT_WORKSPACE_STATE if allow_default else ""

    def _is_valid_workspace_state(self, state: Optional[str]) -> bool:
        try:
            return str(state or "").strip().lower() in WORKSPACE_STATES
        except Exception:
            return False

    # --- Folder CRUD ---

    def create_folder(self, user_id: int, collection_id: str, name: str, icon: Optional[str] = None) -> Dict[str, Any]:
        """יצירת תיקיה חדשה באוסף."""
        try:
            cid = ObjectId(collection_id)
        except Exception:
            return {"ok": False, "error": "collection_id לא תקין"}
        is_valid, error = self._validate_folder_name(name)
        if not is_valid:
            return {"ok": False, "error": error}
        name = str(name).strip()
        if not name:
            return {"ok": False, "error": "שם תיקיה חסר"}
        try:
            col = self.collections.find_one({"_id": cid, "user_id": int(user_id), "is_active": True})
        except Exception:
            col = None
        if not col:
            return {"ok": False, "error": "האוסף לא נמצא"}
        folders = list(col.get("folders") or [])
        if len(folders) >= MAX_FOLDERS_PER_COLLECTION:
            return {"ok": False, "error": f"מקסימום {MAX_FOLDERS_PER_COLLECTION} תיקיות לאוסף"}
        # בדיקת כפילות שם
        existing_names = {str(f.get("name") or "").strip().lower() for f in folders if isinstance(f, dict)}
        if name.strip().lower() in existing_names:
            return {"ok": False, "error": "תיקיה בשם זה כבר קיימת"}
        max_order = max((int(f.get("sort_order") or 0) for f in folders if isinstance(f, dict)), default=0)
        new_folder = {
            "name": name,
            "icon": self._normalize_folder_icon(icon),
            "sort_order": max_order + 1,
        }
        folders.append(new_folder)
        try:
            self.collections.update_one(
                {"_id": cid, "user_id": int(user_id)},
                {"$set": {"folders": folders, "updated_at": _now()}},
            )
            emit_event("collections_folder_create", user_id=int(user_id), collection_id=str(collection_id), folder=name)
            return {"ok": True, "folder": new_folder, "folders": folders}
        except Exception as e:
            emit_event("collections_folder_create_error", severity="error", user_id=int(user_id), error=str(e))
            return {"ok": False, "error": "שגיאה ביצירת תיקיה"}

    def rename_folder(self, user_id: int, collection_id: str, old_name: str, new_name: str, icon: Optional[str] = None) -> Dict[str, Any]:
        """שינוי שם (ואייקון) של תיקיה קיימת. מעדכן גם את הפריטים שמשויכים לתיקיה."""
        try:
            cid = ObjectId(collection_id)
        except Exception:
            return {"ok": False, "error": "collection_id לא תקין"}
        is_valid, error = self._validate_folder_name(new_name)
        if not is_valid:
            return {"ok": False, "error": error}
        old_name = str(old_name or "").strip()
        new_name = str(new_name or "").strip()
        if not old_name or not new_name:
            return {"ok": False, "error": "שם תיקיה חסר"}
        try:
            col = self.collections.find_one({"_id": cid, "user_id": int(user_id), "is_active": True})
        except Exception:
            col = None
        if not col:
            return {"ok": False, "error": "האוסף לא נמצא"}
        folders = list(col.get("folders") or [])
        found_idx = None
        for i, f in enumerate(folders):
            if isinstance(f, dict) and str(f.get("name") or "").strip() == old_name:
                found_idx = i
                break
        if found_idx is None:
            return {"ok": False, "error": "התיקיה לא נמצאה"}
        # בדיקת כפילות (אם השם השתנה)
        if old_name.lower() != new_name.lower():
            existing_names = {str(f.get("name") or "").strip().lower() for j, f in enumerate(folders) if isinstance(f, dict) and j != found_idx}
            if new_name.lower() in existing_names:
                return {"ok": False, "error": "תיקיה בשם זה כבר קיימת"}
        folders[found_idx]["name"] = new_name
        if icon is not None:
            folders[found_idx]["icon"] = self._normalize_folder_icon(icon)
        try:
            self.collections.update_one(
                {"_id": cid, "user_id": int(user_id)},
                {"$set": {"folders": folders, "updated_at": _now()}},
            )
            # עדכון שדה folder בכל הפריטים של התיקיה
            if old_name != new_name:
                try:
                    self.items.update_many(
                        {"collection_id": cid, "user_id": int(user_id), "folder": old_name},
                        {"$set": {"folder": new_name, "updated_at": _now()}},
                    )
                except Exception:
                    # fallback: עדכון אחד אחד
                    try:
                        items_to_update = list(self.items.find({"collection_id": cid, "user_id": int(user_id), "folder": old_name}))
                        for it in items_to_update:
                            self.items.update_one({"_id": it["_id"]}, {"$set": {"folder": new_name, "updated_at": _now()}})
                    except Exception:
                        pass
            emit_event("collections_folder_rename", user_id=int(user_id), collection_id=str(collection_id), old_name=old_name, new_name=new_name)
            return {"ok": True, "folder": folders[found_idx], "folders": folders}
        except Exception as e:
            emit_event("collections_folder_rename_error", severity="error", user_id=int(user_id), error=str(e))
            return {"ok": False, "error": "שגיאה בשינוי שם תיקיה"}

    def delete_folder(self, user_id: int, collection_id: str, folder_name: str) -> Dict[str, Any]:
        """מחיקת תיקיה. הקבצים שבתוכה מועברים ל-root (folder='')."""
        try:
            cid = ObjectId(collection_id)
        except Exception:
            return {"ok": False, "error": "collection_id לא תקין"}
        folder_name = str(folder_name or "").strip()
        if not folder_name:
            return {"ok": False, "error": "שם תיקיה חסר"}
        try:
            col = self.collections.find_one({"_id": cid, "user_id": int(user_id), "is_active": True})
        except Exception:
            col = None
        if not col:
            return {"ok": False, "error": "האוסף לא נמצא"}
        folders = list(col.get("folders") or [])
        new_folders = [f for f in folders if not (isinstance(f, dict) and str(f.get("name") or "").strip() == folder_name)]
        if len(new_folders) == len(folders):
            return {"ok": False, "error": "התיקיה לא נמצאה"}
        try:
            self.collections.update_one(
                {"_id": cid, "user_id": int(user_id)},
                {"$set": {"folders": new_folders, "updated_at": _now()}},
            )
            # העברת קבצים ל-root: בדיקה אם כבר קיים באותו אוסף ב-root
            moved = 0
            removed_duplicates = 0
            try:
                items_in_folder = list(self.items.find({"collection_id": cid, "user_id": int(user_id), "folder": folder_name}))
            except Exception:
                items_in_folder = []
            for it in items_in_folder:
                source = str(it.get("source") or "regular")
                fn = str(it.get("file_name") or "")
                # בדוק אם הפריט כבר קיים ב-root
                existing_root = None
                try:
                    existing_root = self.items.find_one({
                        "collection_id": cid, "user_id": int(user_id),
                        "source": source, "file_name": fn, "folder": "",
                    })
                except Exception:
                    pass
                if existing_root:
                    # הפריט כבר ב-root, מחק את זה שבתיקיה
                    try:
                        self.items.delete_one({"_id": it["_id"]})
                        removed_duplicates += 1
                    except Exception:
                        pass
                else:
                    # העבר ל-root
                    try:
                        self.items.update_one({"_id": it["_id"]}, {"$set": {"folder": "", "updated_at": _now()}})
                        moved += 1
                    except Exception:
                        pass
            # עדכון מונים
            self._refresh_collection_counts(cid, int(user_id))
            emit_event("collections_folder_delete", user_id=int(user_id), collection_id=str(collection_id), folder=folder_name, moved=moved)
            return {"ok": True, "folders": new_folders, "moved": moved, "removed_duplicates": removed_duplicates}
        except Exception as e:
            emit_event("collections_folder_delete_error", severity="error", user_id=int(user_id), error=str(e))
            return {"ok": False, "error": "שגיאה במחיקת תיקיה"}

    def reorder_folders(self, user_id: int, collection_id: str, order: List[str]) -> Dict[str, Any]:
        """סידור מחדש של תיקיות לפי רשימת שמות בסדר הרצוי."""
        try:
            cid = ObjectId(collection_id)
        except Exception:
            return {"ok": False, "error": "collection_id לא תקין"}
        if not isinstance(order, list):
            return {"ok": False, "error": "order חסר"}
        try:
            col = self.collections.find_one({"_id": cid, "user_id": int(user_id), "is_active": True})
        except Exception:
            col = None
        if not col:
            return {"ok": False, "error": "האוסף לא נמצא"}
        folders = list(col.get("folders") or [])
        by_name: Dict[str, Dict[str, Any]] = {}
        for f in folders:
            if isinstance(f, dict):
                by_name[str(f.get("name") or "").strip()] = f
        new_folders = []
        for i, name in enumerate(order):
            name = str(name or "").strip()
            if name in by_name:
                f = dict(by_name.pop(name))
                f["sort_order"] = i + 1
                new_folders.append(f)
        # תיקיות שלא ברשימה נשארות בסוף
        remaining = sorted(by_name.values(), key=lambda f: int(f.get("sort_order") or 0))
        for f in remaining:
            f["sort_order"] = len(new_folders) + 1
            new_folders.append(f)
        try:
            self.collections.update_one(
                {"_id": cid, "user_id": int(user_id)},
                {"$set": {"folders": new_folders, "updated_at": _now()}},
            )
            emit_event("collections_folders_reorder", user_id=int(user_id), collection_id=str(collection_id))
            return {"ok": True, "folders": new_folders}
        except Exception as e:
            emit_event("collections_folders_reorder_error", severity="error", user_id=int(user_id), error=str(e))
            return {"ok": False, "error": "שגיאה בסידור תיקיות"}

    def _refresh_collection_counts(self, cid: Any, user_id: int) -> None:
        """עדכון מונים (items_count, pinned_count) לאוסף."""
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

    def _invalidate_collection_items_cache(self, user_id: int | str, collection_id: Any) -> None:
        cache_obj = cache
        if cache_obj is None:
            return
        try:
            uid = str(user_id).strip()
            cid = str(collection_id).strip()
        except Exception:
            return
        if not uid or not cid:
            return
        try:
            delete_pattern = getattr(cache_obj, "delete_pattern", None)
            if callable(delete_pattern):
                delete_pattern(f"collections_items:{uid}:-api-collections-{cid}-items*")
        except Exception:
            pass

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
            total = int(self.collections.count_documents({"user_id": int(user_id), "is_active": True}))
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
                {"_id": cid, "user_id": user_id, "is_active": True},
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
                {"_id": cid, "user_id": user_id, "is_active": True},
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

        flt = {"user_id": user_id, "is_active": True}

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
        # ולידציית תגיות מוקדמת כדי למנוע כתיבות חלקיות
        for it in items:
            if not isinstance(it, dict):
                continue
            file_name = str(it.get("file_name") or "").strip()
            if not file_name:
                continue
            tags_provided = "tags" in it
            tags = it.get("tags") if tags_provided else None
            is_valid, error = self._validate_tags(tags)
            if not is_valid:
                raise ValueError(f"Invalid tags for {file_name}: {error}")

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

                tags_provided = isinstance(it, dict) and "tags" in it
                tags = it.get("tags") if tags_provided else None

                # ולידציית תגיות
                is_valid, error = self._validate_tags(tags)
                if not is_valid:
                    raise ValueError(f"Invalid tags for {file_name}: {error}")

                tags_to_store = [] if tags is None else tags

                folder = self._normalize_folder(it.get("folder"))

                # נסה קודם לעדכן פריט קיים; אם לא קיים – נכניס חדש
                query = {
                    "collection_id": cid,
                    "user_id": int(user_id),
                    "source": source,
                    "file_name": file_name,
                    "folder": folder,
                }

                set_fields: Dict[str, Any] = {"updated_at": now}
                if "note" in it:
                    set_fields["note"] = str(it.get("note") or "")[:500]
                if "pinned" in it:
                    set_fields["pinned"] = bool(it.get("pinned"))
                if "custom_order" in it:
                    set_fields["custom_order"] = it.get("custom_order")
                if "workspace_state" in it:
                    set_fields["workspace_state"] = self._normalize_workspace_state(it.get("workspace_state"))
                if tags_provided:
                    set_fields["tags"] = tags_to_store

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
                    "folder": folder,
                    "note": str(it.get("note") or "")[:500],
                    "tags": tags_to_store,
                    "pinned": bool(it.get("pinned") or False),
                    "custom_order": it.get("custom_order"),
                    "workspace_state": self._normalize_workspace_state(it.get("workspace_state")),
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
            except ValueError:
                raise
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

    def move_item_folder(
        self, user_id: int, collection_id: str,
        source: str, file_name: str,
        old_folder: str, new_folder: str,
    ) -> Dict[str, Any]:
        """העברת פריט מתיקיה אחת לאחרת, תוך שמירה על כל המטאדאטה."""
        try:
            cid = ObjectId(collection_id)
        except Exception:
            return {"ok": False, "error": "collection_id לא תקין"}
        source = str(source or "regular").lower()
        file_name = str(file_name or "").strip()
        if not file_name:
            return {"ok": False, "error": "file_name חסר"}
        old_f = self._normalize_folder(old_folder)
        new_f = self._normalize_folder(new_folder)
        if old_f == new_f:
            return {"ok": True, "moved": 0}
        try:
            res = self.items.update_one(
                {"collection_id": cid, "user_id": int(user_id), "source": source, "file_name": file_name, "folder": old_f},
                {"$set": {"folder": new_f, "updated_at": _now()}},
            )
            matched = int(getattr(res, "matched_count", 0) or 0)
            return {"ok": True, "moved": matched}
        except DuplicateKeyError:
            # הפריט כבר קיים בתיקיית היעד – ממזגים מטא-דאטה ומוחקים את המקור
            src = self.items.find_one(
                {"collection_id": cid, "user_id": int(user_id), "source": source, "file_name": file_name, "folder": old_f},
            )
            if src:
                merge: dict = {}
                for field in ("note", "tags", "pinned", "workspace_state"):
                    val = src.get(field)
                    if val is not None:
                        merge[field] = val
                if merge:
                    merge["updated_at"] = _now()
                    self.items.update_one(
                        {"collection_id": cid, "user_id": int(user_id), "source": source, "file_name": file_name, "folder": new_f},
                        {"$set": merge},
                    )
                self.items.delete_one({"_id": src["_id"]})
                self._refresh_collection_counts(cid, int(user_id))
            return {"ok": True, "moved": 1}
        except Exception as e:
            logger.error("move_item_folder error: %s", e)
            return {"ok": False, "error": "שגיאה בהעברת פריט"}

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
                folder = self._normalize_folder(it.get("folder"))
                res = self.items.delete_one({"collection_id": cid, "user_id": user_id, "source": source, "file_name": file_name, "folder": folder})
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

    def update_item_tags(self, user_id: int, item_id: str, tags: Any) -> Optional[Dict[str, Any]]:
        """
        עדכון תגיות של פריט קיים באוסף.

        Args:
            user_id: מזהה משתמש
            item_id: מזהה הפריט (collection_item _id)
            tags: רשימת תגיות חדשה

        Returns:
            dict: הפריט המעודכן או None
        """
        # ולידציה
        is_valid, error = self._validate_tags(tags)
        if not is_valid:
            raise ValueError(f"Invalid tags: {error}")

        try:
            item_id_obj = ObjectId(item_id)
        except Exception:
            return None

        new_tags = [] if tags is None else list(tags)

        # שליפת מצב קודם לצורך דלתא/אנליטיקה
        try:
            current_item = self.items.find_one({"_id": item_id_obj, "user_id": user_id})
        except Exception:
            current_item = None
        if not current_item:
            return None
        old_tags = list(current_item.get("tags") or [])

        # עדכון במסד הנתונים
        result = self.items.update_one(
            {
                "_id": item_id_obj,
                "user_id": user_id,  # ACL check
            },
            {
                "$set": {
                    "tags": new_tags,
                    "updated_at": _now(),
                }
            },
        )

        matched = int(getattr(result, "matched_count", 0) or 0)
        if matched <= 0:
            matched = int(getattr(result, "modified_count", 0) or 0)
        if matched <= 0:
            return None

        # קריאת הפריט המעודכן
        try:
            item = self.items.find_one({"_id": item_id_obj})
        except Exception:
            item = None

        # ביטול cache
        if item:
            cid = item.get("collection_id")
            try:
                self._invalidate_collection_items_cache(user_id, cid)
            except Exception:
                pass
            cache_obj = cache
            if cache_obj is not None:
                try:
                    uid = str(user_id).strip()
                    cid_str = str(cid).strip()
                    if uid and cid_str:
                        cache_obj.delete_pattern(f"collections_detail:{uid}:-api-collections-{cid_str}*")
                except Exception:
                    pass

        # אירועים אנליטיים
        emit_event(
            "collections_item_tags_update",
            user_id=int(user_id),
            item_id=str(item_id),
            tags=list(new_tags),
        )
        added = sorted(set(new_tags) - set(old_tags))
        removed = sorted(set(old_tags) - set(new_tags))
        if added:
            emit_event(
                "collections_tags_added",
                user_id=int(user_id),
                item_id=str(item_id),
                tags=list(added),
                count=int(len(added)),
            )
        if removed:
            emit_event(
                "collections_tags_removed",
                user_id=int(user_id),
                item_id=str(item_id),
                tags=list(removed),
                count=int(len(removed)),
            )

        return self._public_item(item) if item else None

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
                folder = self._normalize_folder(it.get("folder"))
                entry: Dict[str, Any] = {"source": source, "file_name": file_name}
                if folder:
                    entry["folder"] = folder
                new_items.append(entry)
            except Exception:
                continue

        # Apply custom_order per item (pos starts at 1) without bulk
        pos = 1
        had_update_error = False
        first_error_message: Optional[str] = None
        for it in new_items:
            try:
                q: Dict[str, Any] = {"collection_id": cid, "user_id": user_id, "source": it["source"], "file_name": it["file_name"]}
                if "folder" in it:
                    q["folder"] = it["folder"]
                else:
                    q["folder"] = ""
                res = self.items.update_one(
                    q,
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
                "is_active": True,
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

    def get_tags_metadata(self) -> Dict[str, Any]:
        """
        החזרת מטאדאטה על כל התגיות הזמינות.

        Returns:
            dict: {
                "allowed_tags": [...],
                "categories": {...},
                "metadata": {...}
            }
        """
        cache_key = "collections:tags_metadata"
        cache_obj = cache
        if cache_obj is not None:
            try:
                cached = cache_obj.get(cache_key)
                if isinstance(cached, dict) and cached.get("allowed_tags"):
                    return cached
            except Exception:
                pass
        payload = {
            "allowed_tags": ALLOWED_TAGS,
            "categories": TAG_CATEGORIES,
            "metadata": TAG_METADATA,
        }
        if cache_obj is not None:
            try:
                cache_obj.set(cache_key, payload, expire_seconds=3600)
            except Exception:
                pass
        return payload

    def get_collection_items(
        self,
        user_id: int,
        collection_id: str,
        *,
        page: int = 1,
        per_page: int = 20,
        include_computed: bool = True,
        fetch_all: bool = False,
        folder_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        t_total_start = time.perf_counter()
        t_find_collection = 0.0
        t_fetch_manual = 0.0
        t_compute_smart = 0.0
        t_compute_active = 0.0
        t_public_map = 0.0
        try:
            cid = ObjectId(collection_id)
        except Exception:
            return {"ok": False, "error": "collection_id לא תקין"}
        try:
            # שליפת אוסף לקבלת המוד והחוקים
            t0 = time.perf_counter()
            try:
                col = self.collections.find_one(
                    {"_id": cid, "user_id": user_id},
                    projection={"mode": 1, "rules": 1},
                )
            except TypeError:
                # תאימות לסטאבים/מימושים ללא projection=
                col = self.collections.find_one({"_id": cid, "user_id": user_id})
            t_find_collection = max(0.0, time.perf_counter() - t0)
            if not col:
                return {"ok": False, "error": "האוסף לא נמצא"}
            mode = str(col.get("mode") or "manual").lower()
            rules = dict(col.get("rules") or {})

            # פריטים ידניים
            t0 = time.perf_counter()
            manual_query: Dict[str, Any] = {"collection_id": cid, "user_id": user_id}
            # סינון אופציונלי לפי תיקיה
            if folder_filter is not None:
                manual_query["folder"] = self._normalize_folder(folder_filter)
            manual_projection = {
                "collection_id": 1,
                "user_id": 1,
                "source": 1,
                "file_name": 1,
                "folder": 1,
                "note": 1,
                "tags": 1,
                "pinned": 1,
                "custom_order": 1,
                "workspace_state": 1,
                "added_at": 1,
                "updated_at": 1,
            }
            try:
                manual_cur = self.items.find(manual_query, projection=manual_projection)
            except TypeError:
                manual_cur = self.items.find(manual_query)
            manual_list: List[Dict[str, Any]] = list(manual_cur) if not isinstance(manual_cur, list) else manual_cur
            t_fetch_manual = max(0.0, time.perf_counter() - t0)
            manual_total = len(manual_list)

            # פריטים חכמים (ע"פ חוקים)
            computed: List[Dict[str, Any]] = []
            if include_computed and mode in {"smart", "mixed"}:
                t0 = time.perf_counter()
                computed = self.compute_smart_items(user_id, rules, limit=200)
                t_compute_smart = max(0.0, time.perf_counter() - t0)
            comp_total = len(computed)

            out_items: List[Dict[str, Any]] = []
            if mode == "manual":
                out_items = manual_list
            elif mode == "smart":
                out_items = computed
            else:  # mixed
                seen: set[Tuple[str, str]] = set()
                # כל הפריטים הידניים נכנסים — אותו קובץ יכול להופיע בתיקיות שונות.
                # ה-seen משמש רק לסנן computed כפולים של פריטים ידניים.
                for m in manual_list:
                    key = (str(m.get("source") or "regular"), str(m.get("file_name") or ""))
                    seen.add(key)
                    out_items.append(m)
                for c in computed:
                    key = (str(c.get("source") or "regular"), str(c.get("file_name") or ""))
                    if key in seen:
                        continue
                    seen.add(key)
                    out_items.append(c)

            # מיון בסיסי: root קודם, אח"כ תיקיות לפי שם, בתוך כל קבוצה – pinned > custom_order > file_name
            def _sort_key(d: Dict[str, Any]):
                folder_val = str(d.get("folder") or "")
                # root items (folder ריק) קודמים
                folder_rank = 0 if not folder_val else 1
                # ודא שסדר מותאם אישית יילקח גם אם נשמר כמחרוזת ספרתית (למשל ע"י FakeDB)
                co_raw = d.get("custom_order")
                try:
                    # המרה בטוחה ל-int; אם אין ערך/לא מספרי — קבע ערך גדול כדי שימוין לאחרים
                    co_val = int(co_raw)
                except Exception:
                    co_val = 1_000_000
                return (
                    folder_rank,
                    folder_val.lower(),
                    0 if bool(d.get("pinned")) else 1,
                    co_val,
                    str(d.get("file_name") or "").lower(),
                )

            out_items.sort(key=_sort_key)

            # דפדוף
            if fetch_all:
                p = 1
                pp = len(out_items)
                page_items = list(out_items)
            else:
                try:
                    p = max(1, int(page or 1))
                    pp = max(1, min(200, int(per_page or 20)))
                except Exception:
                    p, pp = 1, 20
                start = (p - 1) * pp
                end = start + pp
                page_items = out_items[start:end]

            # חישוב סטטוס פעילות קובץ (Data integrity): ערך בוליאני is_file_active
            try:
                t0 = time.perf_counter()
                active_map: Dict[Tuple[str, str], bool] = {}
                # אסוף זוגות ייחודיים (source, file_name) מהעמוד בלבד
                uniq: List[Tuple[str, str]] = []
                seen_keys: set[Tuple[str, str]] = set()
                for it in page_items:
                    src = str(it.get("source") or "regular")
                    fn = str(it.get("file_name") or "")
                    if not fn:
                        continue
                    k = (src, fn)
                    if k not in seen_keys:
                        seen_keys.add(k)
                        uniq.append(k)

                # אופטימיזציה: הימנעות מ-N+1 (find_one לכל פריט).
                # נבצע עד 2 שאילתות (regular/large) עם $in על file_name.
                def _mark_all(source: str, names: set[str], value: bool) -> None:
                    for _fn in names:
                        active_map[(source, _fn)] = bool(value)

                def _batch_active_names(coll: Any, names: set[str]) -> set[str]:
                    # החזר קבוצת file_name שקיימים כ"פעילים". אם נכשל – זרוק חריגה כדי לאפשר fail-open.
                    query = {
                        "user_id": int(user_id),
                        "file_name": {"$in": list(names)},
                        # לאחר המיגרציה: פילטר ישיר וידידותי לאינדקסים
                        "is_active": True,
                    }
                    # מספיק לנו רק file_name
                    projection = {"file_name": 1}
                    rows = coll.find(query, projection=projection)
                    docs = list(rows) if not isinstance(rows, list) else rows
                    out: set[str] = set()
                    for d in docs:
                        if not isinstance(d, dict):
                            continue
                        fnv = d.get("file_name")
                        if fnv:
                            out.add(str(fnv))
                    return out

                regular_names: set[str] = set()
                large_names: set[str] = set()
                for src, fn in uniq:
                    if str(src).lower() == "large":
                        large_names.add(fn)
                    else:
                        regular_names.add(fn)

                # regular
                if regular_names:
                    if self.code_snippets is None:
                        _mark_all("regular", regular_names, True)
                    else:
                        try:
                            active_regular = _batch_active_names(self.code_snippets, regular_names)
                            for fn in regular_names:
                                active_map[("regular", fn)] = bool(fn in active_regular)
                        except Exception:
                            # fail-open: אם יש כשל במסד – נניח פעיל כדי לא להסתיר פריטים
                            _mark_all("regular", regular_names, True)

                # large
                if large_names:
                    if self.large_files is None:
                        # תאימות להתנהגות קודמת:
                        # כאשר large_files לא קיים, נסה לבדוק קיום דרך code_snippets (אם זמין).
                        # זה מאפשר "graceful degradation" בסביבות ללא large_files.
                        if self.code_snippets is None:
                            _mark_all("large", large_names, True)
                        else:
                            try:
                                active_large_fallback = _batch_active_names(self.code_snippets, large_names)
                                for fn in large_names:
                                    active_map[("large", fn)] = bool(fn in active_large_fallback)
                            except Exception:
                                # fail-open: אם יש כשל במסד – נניח פעיל כדי לא להסתיר פריטים
                                _mark_all("large", large_names, True)
                    else:
                        try:
                            active_large = _batch_active_names(self.large_files, large_names)
                            for fn in large_names:
                                active_map[("large", fn)] = bool(fn in active_large)
                        except Exception:
                            # fail-open: אם יש כשל במסד – נניח פעיל כדי לא להסתיר פריטים
                            _mark_all("large", large_names, True)

                # שכבת תאימות: אם מקור נשמר בערך שאינו בדיוק "regular"/"large" (למשל רישיות),
                # שייך אותו למפה לפי הנירמול הלוגי כדי שה-lookup בהמשך יצליח.
                for src, fn in uniq:
                    key = (src, fn)
                    if key in active_map:
                        continue
                    src_norm = "large" if str(src).lower() == "large" else "regular"
                    active_map[key] = bool(active_map.get((src_norm, fn), True))
                t_compute_active = max(0.0, time.perf_counter() - t0)
            except Exception:
                active_map = {}

            # החזרה (כולל is_file_active לכל פריט)
            t0 = time.perf_counter()
            items_out: List[Dict[str, Any]] = []
            for x in page_items:
                item_pub = self._public_item(x)
                key = (str(item_pub.get("source") or "regular"), str(item_pub.get("file_name") or ""))
                item_pub["is_file_active"] = bool(active_map.get(key, True))
                items_out.append(item_pub)
            t_public_map = max(0.0, time.perf_counter() - t0)

            result = {
                "ok": True,
                "items": items_out,
                "page": p,
                "per_page": pp,
                "total_manual": manual_total,
                "total_computed": comp_total,
                "total_items": len(out_items),
            }
            # דיבוג ביצועים: לדווח רק אם איטי (או אם הופעל env)
            try:
                slow_ms_env = os.getenv("COLLECTIONS_GET_ITEMS_SLOW_MS", "")
                slow_ms = float(slow_ms_env) if slow_ms_env not in (None, "") else 500.0
            except Exception:
                slow_ms = 500.0
            total_ms = max(0.0, (time.perf_counter() - t_total_start) * 1000.0)
            if total_ms >= float(slow_ms or 0.0):
                try:
                    emit_event(
                        "collections_get_items_perf",
                        severity="warn",
                        user_id=int(user_id),
                        collection_id=str(collection_id),
                        mode=str(mode),
                        include_computed=bool(include_computed),
                        page=int(p),
                        per_page=int(pp),
                        total_ms=round(total_ms, 1),
                        db_find_collection_ms=round(t_find_collection * 1000.0, 1),
                        db_fetch_manual_ms=round(t_fetch_manual * 1000.0, 1),
                        compute_smart_ms=round(t_compute_smart * 1000.0, 1),
                        compute_active_ms=round(t_compute_active * 1000.0, 1),
                        map_public_ms=round(t_public_map * 1000.0, 1),
                        items_returned=int(len(items_out)),
                        manual_total=int(manual_total),
                        computed_total=int(comp_total),
                        total_items=int(len(out_items)),
                        handled=True,
                    )
                except Exception:
                    pass
                try:
                    logger.warning(
                        "collections_get_items_slow total_ms=%.1f mode=%s items=%s manual=%s computed=%s",
                        total_ms,
                        str(mode),
                        len(items_out),
                        manual_total,
                        comp_total,
                    )
                except Exception:
                    pass
            return result
        except Exception as e:
            emit_event("collections_get_items_error", severity="error", user_id=int(user_id), error=str(e))
            return {"ok": False, "error": "שגיאה בשליפת פריטים"}

    def update_workspace_item_state(self, user_id: int, item_id: str, state: str) -> Dict[str, Any]:
        try:
            uid = int(user_id)
        except Exception:
            return {"ok": False, "error": "invalid_user"}
        if not self._is_valid_workspace_state(state):
            return {"ok": False, "error": "invalid_workspace_state"}
        try:
            iid = ObjectId(item_id)
        except Exception:
            return {"ok": False, "error": "invalid_item_id"}
        try:
            item = self.items.find_one({"_id": iid, "user_id": uid})
        except Exception:
            item = None
        if not item:
            return {"ok": False, "error": "workspace_item_not_found"}
        collection_id = item.get("collection_id")
        if collection_id is None:
            return {"ok": False, "error": "workspace_collection_missing"}
        try:
            workspace_doc = self.collections.find_one({
                "_id": collection_id,
                "user_id": uid,
                "name": "שולחן עבודה",
                "is_active": True,
            })
        except Exception:
            workspace_doc = None
        if not workspace_doc:
            return {"ok": False, "error": "workspace_item_not_found"}
        next_state = self._normalize_workspace_state(state)
        try:
            res = self.items.update_one(
                {"_id": iid, "user_id": uid},
                {"$set": {"workspace_state": next_state, "updated_at": _now()}},
            )
            matched = int(getattr(res, "matched_count", 0) or 0)
            if matched <= 0:
                matched = int(getattr(res, "modified_count", 0) or 0)
            if matched <= 0:
                return {"ok": False, "error": "workspace_item_not_found"}
        except Exception as e:
            emit_event(
                "workspace_state_update_error",
                severity="error",
                user_id=uid,
                item_id=str(item_id),
                error=str(e),
            )
            return {"ok": False, "error": "workspace_state_update_failed"}
        self._invalidate_collection_items_cache(uid, collection_id)
        emit_event("workspace_state_update", user_id=uid, item_id=str(item_id), state=next_state)
        return {"ok": True, "item_id": str(iid), "state": next_state}

    def compute_smart_items(self, user_id: int, rules: Dict[str, Any], limit: int = 200) -> List[Dict[str, Any]]:
        """הפקת פריטים על בסיס חוקים פשוטים מתוך אוסף code_snippets.

        כל פריט מוחזר בפורמט: {source: "regular", file_name: str}
        """
        if self.code_snippets is None:
            return []
        try:
            flt: Dict[str, Any] = {"user_id": int(user_id), "is_active": True}
            q = str(rules.get("query") or "").strip()
            if q:
                flt["$text"] = {"$search": q}
            lang = str(rules.get("programming_language") or "").strip()
            if lang:
                flt["programming_language"] = lang
            tags = rules.get("tags")
            tag_values = [str(t) for t in tags if isinstance(t, str) and t] if isinstance(tags, list) else []
            if tag_values:
                flt["tags"] = {"$all": tag_values}
            repo_tag = str(rules.get("repo_tag") or "").strip()
            if repo_tag:
                flt.setdefault("tags", {})
                # אם כבר יש $all, ודא שהתנאי כולל גם repo_tag; אחרת קבע חיתוך פשוט
                if isinstance(flt["tags"], dict) and "$all" in flt["tags"]:
                    arr = list(flt["tags"]["$all"])
                    if repo_tag not in arr:
                        arr.append(repo_tag)
                    flt["tags"]["$all"] = arr
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
        share_raw = d.get("share")
        share_dict: Dict[str, Any]
        if isinstance(share_raw, dict):
            share_dict = dict(share_raw)
        else:
            share_dict = {}
        share_dict.pop("visibility", None)
        share_enabled = bool(share_dict.get("enabled", False))
        token_val = share_dict.get("token")
        if token_val is not None:
            try:
                token_val = str(token_val)
            except Exception:
                token_val = None

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
            "share": {
                "enabled": share_enabled,
                "token": token_val,
            },
            "folders": list(d.get("folders") or []),
        }

    def _public_item(self, d: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": str(d.get("_id")) if d.get("_id") is not None else None,
            "collection_id": (str(d.get("collection_id")) if d.get("collection_id") is not None else None),
            "user_id": int(d.get("user_id") or 0),
            "source": str(d.get("source") or "regular"),
            "file_name": d.get("file_name"),
            "folder": str(d.get("folder") or ""),
            "note": d.get("note") or "",
            "tags": list(d.get("tags") or []),
            "pinned": bool(d.get("pinned", False)),
            "custom_order": d.get("custom_order"),
            "workspace_state": self._normalize_workspace_state(d.get("workspace_state")),
            "added_at": (d.get("added_at").isoformat() if isinstance(d.get("added_at"), datetime) else None),
            "updated_at": (d.get("updated_at").isoformat() if isinstance(d.get("updated_at"), datetime) else None),
        }

    # --- Sharing helpers ---
    def set_share(self, user_id: int, collection_id: str, enabled: bool) -> Dict[str, Any]:
        """הפעלה/ביטול שיתוף לאוסף. יוצר token אם נדרש."""
        try:
            cid = ObjectId(collection_id)
        except Exception:
            return {"ok": False, "error": "collection_id לא תקין"}

        try:
            # שלוף כדי לבדוק token קיים
            doc = self.collections.find_one({"_id": cid, "user_id": int(user_id)})
            if not doc:
                return {"ok": False, "error": "האוסף לא נמצא"}
            share = dict(doc.get("share") or {})
            token = share.get("token")
            if enabled and not token:
                try:
                    import secrets
                    token = secrets.token_urlsafe(16)
                except Exception:
                    import uuid
                    token = uuid.uuid4().hex
            token_str: Optional[str]
            if token is None:
                token_str = None
            else:
                try:
                    token_str = str(token)
                except Exception:
                    token_str = None
            new_share = {
                "enabled": bool(enabled),
                "token": token_str,
            }
            self.collections.update_one(
                {"_id": cid, "user_id": int(user_id)},
                {"$set": {"share": new_share, "updated_at": _now()}},
            )
            emit_event("collections_share_update", user_id=int(user_id), collection_id=str(collection_id), enabled=bool(enabled))
            # החזר מיפוי ציבורי עדכני
            doc["share"] = new_share
            return {"ok": True, "collection": self._public_collection(doc)}
        except Exception as e:
            emit_event("collections_share_update_error", severity="error", user_id=int(user_id), error=str(e))
            return {"ok": False, "error": "שגיאה בעדכון שיתוף"}

    def get_collection_by_share_token(self, token: str) -> Dict[str, Any]:
        """שליפת אוסף לשיתוף ציבורי לפי token.

        מחזיר {ok, collection} ללא אימות משתמש. אם לא נמצא – ok=False.
        """
        if not token:
            return {"ok": False, "error": "token חסר"}
        try:
            doc = self.collections.find_one({
                "share.token": str(token),
                "share.enabled": True,
                "is_active": True,
            })
            if not doc:
                return {"ok": False, "error": "לא נמצא"}
            return {"ok": True, "collection": self._public_collection(doc)}
        except Exception:
            return {"ok": False, "error": "שגיאה בשליפה"}

    # --- Sharing advanced helpers ---

    def _fetch_regular_file(self, user_id: int, file_name: str, *, include_code: bool = False) -> Optional[Dict[str, Any]]:
        if self.code_snippets is None:
            return None
        query = {
            "user_id": int(user_id),
            "file_name": str(file_name),
            "is_active": True,
        }
        projection = None if include_code else {"code": 0}
        doc: Optional[Dict[str, Any]] = None
        try:
            doc_found = self.code_snippets.find_one(query, projection=projection, sort=[("version", -1), ("updated_at", -1), ("_id", -1)])
            if doc_found is not None:
                doc = dict(doc_found)
        except TypeError:
            try:
                doc_found = self.code_snippets.find_one(query)
                if doc_found is not None:
                    doc = dict(doc_found)
            except Exception:
                doc = None
        except Exception:
            doc = None
        if doc is None:
            try:
                raw = self.code_snippets.find(query, projection=projection)
                docs_list = list(raw) if not isinstance(raw, list) else raw
                if docs_list:
                    def _sort_key(d: Dict[str, Any]) -> Tuple[int, float]:
                        try:
                            ver = int(d.get("version") or 0)
                        except Exception:
                            ver = 0
                        ts_raw = d.get("updated_at") or d.get("created_at")
                        try:
                            ts = float(ts_raw.timestamp()) if hasattr(ts_raw, "timestamp") else 0.0
                        except Exception:
                            ts = 0.0
                        return (ver, ts)

                    docs_list = [dict(d) for d in docs_list]
                    docs_list.sort(key=_sort_key, reverse=True)
                    doc = docs_list[0]
            except Exception:
                doc = None
        if doc is None:
            return None
        if not include_code and "code" in doc:
            doc.pop("code", None)
        return doc

    def _fetch_large_file(self, user_id: int, file_name: str, *, include_content: bool = False) -> Optional[Dict[str, Any]]:
        if self.large_files is None:
            return None
        query = {
            "user_id": int(user_id),
            "file_name": str(file_name),
            "is_active": True,
        }
        projection = None if include_content else {"content": 0}
        doc: Optional[Dict[str, Any]] = None
        try:
            doc_found = self.large_files.find_one(query, projection=projection, sort=[("updated_at", -1), ("_id", -1)])
            if doc_found is not None:
                doc = dict(doc_found)
        except TypeError:
            try:
                doc_found = self.large_files.find_one(query)
                if doc_found is not None:
                    doc = dict(doc_found)
            except Exception:
                doc = None
        except Exception:
            doc = None
        if doc is None:
            try:
                raw = self.large_files.find(query, projection=projection)
                docs_list = list(raw) if not isinstance(raw, list) else raw
                if docs_list:
                    def _sort_key(d: Dict[str, Any]) -> float:
                        ts_raw = d.get("updated_at") or d.get("created_at")
                        try:
                            return float(ts_raw.timestamp()) if hasattr(ts_raw, "timestamp") else 0.0
                        except Exception:
                            return 0.0

                    docs_list = [dict(d) for d in docs_list]
                    docs_list.sort(key=_sort_key, reverse=True)
                    doc = docs_list[0]
            except Exception:
                doc = None
        if doc is None:
            return None
        if not include_content and "content" in doc:
            doc.pop("content", None)
        return doc

    def resolve_share_doc_refs(
        self,
        user_id: int,
        items: List[Dict[str, Any]],
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[Tuple[str, str], Dict[str, Any]]]:
        by_doc: Dict[str, Dict[str, Any]] = {}
        by_key: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for it in items:
            try:
                source_raw = it.get("source")
                source = str(source_raw or "regular").lower()
            except Exception:
                source = "regular"
            file_name = str(it.get("file_name") or "").strip()
            if not file_name:
                continue
            if source == "large":
                doc_meta = self._fetch_large_file(user_id, file_name, include_content=False)
            else:
                doc_meta = self._fetch_regular_file(user_id, file_name, include_code=False)
                source = "regular"
            if not isinstance(doc_meta, dict):
                continue
            doc_id_raw = doc_meta.get("_id")
            try:
                doc_id = str(doc_id_raw)
            except Exception:
                doc_id = None
            if not doc_id:
                continue
            info = {
                "doc_id": doc_id,
                "source": source,
                "file_name": file_name,
                "language": str(doc_meta.get("programming_language") or "text"),
                "description": doc_meta.get("description") or "",
                "tags": list(doc_meta.get("tags") or []),
                "updated_at": doc_meta.get("updated_at"),
                "created_at": doc_meta.get("created_at"),
                "file_size": doc_meta.get("file_size"),
                "lines_count": doc_meta.get("lines_count"),
                "metadata": doc_meta,
            }
            by_doc[doc_id] = info
            by_key[(source, file_name)] = info
        return by_doc, by_key

    def get_share_context(self, token: str) -> Dict[str, Any]:
        base = self.get_collection_by_share_token(token)
        if not base.get("ok"):
            return {"ok": False, "error": base.get("error", "לא נמצא")}
        collection = base.get("collection") or {}
        owner_id = collection.get("user_id")
        collection_id = collection.get("id")
        if owner_id is None or collection_id is None:
            return {"ok": False, "error": "לא נמצא"}
        items_res = self.get_collection_items(owner_id, collection_id, page=1, per_page=200, include_computed=True, fetch_all=True)
        if not items_res.get("ok"):
            return {"ok": False, "error": items_res.get("error", "שגיאה בשליפת פריטים")}
        items = items_res.get("items") or []
        by_doc, by_key = self.resolve_share_doc_refs(owner_id, items)
        return {
            "ok": True,
            "collection": collection,
            "owner_id": owner_id,
            "collection_id": collection_id,
            "items": items,
            "items_result": items_res,
            "doc_refs": by_doc,
            "doc_refs_by_key": by_key,
        }

    def get_shared_file_details(self, token: str, file_id: str) -> Dict[str, Any]:
        ctx = self.get_share_context(token)
        if not ctx.get("ok"):
            return ctx
        doc_refs: Dict[str, Dict[str, Any]] = ctx.get("doc_refs", {})
        meta = doc_refs.get(str(file_id))
        if not isinstance(meta, dict):
            return {"ok": False, "error": "לא נמצא"}
        owner_id = ctx.get("owner_id")
        if owner_id is None:
            return {"ok": False, "error": "לא נמצא"}
        source = meta.get("source", "regular") or "regular"
        file_name = meta.get("file_name") or ""
        if source == "large":
            full_doc = self._fetch_large_file(owner_id, file_name, include_content=True)
            content_field = "content"
        else:
            full_doc = self._fetch_regular_file(owner_id, file_name, include_code=True)
            content_field = "code"
            source = "regular"
        if not isinstance(full_doc, dict):
            return {"ok": False, "error": "לא נמצא"}
        raw_content = full_doc.get(content_field)
        if not isinstance(raw_content, str):
            raw_content = ""
        size_bytes = len(raw_content.encode("utf-8", errors="ignore")) if raw_content else 0
        lines_count = len(raw_content.splitlines())
        payload = {
            "id": str(full_doc.get("_id")),
            "file_name": file_name,
            "language": str(full_doc.get("programming_language") or meta.get("language") or "text"),
            "description": full_doc.get("description") or meta.get("description") or "",
            "tags": list(full_doc.get("tags") or meta.get("tags") or []),
            "created_at": full_doc.get("created_at") or meta.get("created_at"),
            "updated_at": full_doc.get("updated_at") or meta.get("updated_at"),
            "size_bytes": size_bytes,
            "lines_count": lines_count,
            "source": source,
            "content": raw_content,
        }
        return {
            "ok": True,
            "collection": ctx.get("collection"),
            "file": payload,
            "context": ctx,
        }

    def collect_shared_documents(self, token: str) -> Dict[str, Any]:
        ctx = self.get_share_context(token)
        if not ctx.get("ok"):
            return ctx
        owner_id = ctx.get("owner_id")
        docs: List[Dict[str, Any]] = []
        if owner_id is None:
            return {"ok": False, "error": "לא נמצא"}
        for meta in ctx.get("doc_refs", {}).values():
            if not isinstance(meta, dict):
                continue
            source = meta.get("source", "regular") or "regular"
            file_name = meta.get("file_name") or ""
            if source == "large":
                full_doc = self._fetch_large_file(owner_id, file_name, include_content=True)
                content_field = "content"
            else:
                full_doc = self._fetch_regular_file(owner_id, file_name, include_code=True)
                content_field = "code"
                source = "regular"
            if not isinstance(full_doc, dict):
                continue
            raw_content = full_doc.get(content_field)
            if not isinstance(raw_content, str):
                raw_content = ""
            docs.append({
                "id": str(full_doc.get("_id")),
                "file_name": file_name,
                "content": raw_content,
                "language": str(full_doc.get("programming_language") or meta.get("language") or "text"),
                "description": full_doc.get("description") or meta.get("description") or "",
                "tags": list(full_doc.get("tags") or meta.get("tags") or []),
                "source": source,
                "size_bytes": len(raw_content.encode("utf-8", errors="ignore")) if raw_content else 0,
                "lines_count": len(raw_content.splitlines()),
            })
        return {
            "ok": True,
            "collection": ctx.get("collection"),
            "documents": docs,
            "context": ctx,
        }

    def log_share_activity(
        self,
        token: str,
        *,
        collection_id: Optional[str] = None,
        file_id: Optional[str] = None,
        event: str = "view",
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        try:
            emit_event(
                "collections_share_activity",
                operation=str(event),
                token=str(token),
                collection_id=str(collection_id) if collection_id is not None else None,
                file_id=str(file_id) if file_id is not None else None,
                ip=ip,
                user_agent=user_agent,
            )
        except Exception:
            pass
        collection = getattr(self, "share_activity", None)
        if collection is None:
            return
        try:
            record = {
                "token": str(token),
                "collection_id": str(collection_id) if collection_id is not None else None,
                "file_id": str(file_id) if file_id is not None else None,
                "event": str(event),
                "ip": ip,
                "user_agent": user_agent,
                "created_at": _now(),
            }
            record = {k: v for k, v in record.items() if v not in (None, "")}
            collection.insert_one(record)
        except Exception:
            return
