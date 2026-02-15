"""
Personal Backup Service – ייצוא ושחזור גיבוי אישי מלא.
"""
import json
import logging
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---- Observability (fail-open) ----
try:
    from observability import emit_event
except Exception:

    def emit_event(event: str, severity: str = "info", **fields):
        return None


# גרסת פורמט הגיבוי — מאפשר לזהות שינויים עתידיים במבנה
BACKUP_FORMAT_VERSION = 1

# גודל מקסימלי של ZIP לשחזור (100MB דחוס)
MAX_RESTORE_ZIP_SIZE = 100 * 1024 * 1024

# גודל מקסימלי של תוכן לא-דחוס (500MB) — הגנה מפני zip bombs
MAX_UNCOMPRESSED_SIZE = 500 * 1024 * 1024

# גודל מקסימלי לקובץ בודד לא-דחוס (50MB)
MAX_SINGLE_FILE_SIZE = 50 * 1024 * 1024

# מגבלות ייצוא כדי להימנע מ-OOM
BOOKMARKS_EXPORT_LIMIT = 5000
STICKY_NOTES_EXPORT_LIMIT = 5000

# שדות מותריים לשחזור ב-user_preferences (allowlist)
USER_PREFERENCES_ALLOWLIST = {
    "attention_settings": {
        "enabled",
        "stale_days",
        "max_items_per_group",
        "show_missing_description",
        "show_missing_tags",
        "show_stale_files",
    }
}


class PersonalBackupService:
    """מנגנון ייצוא ושחזור גיבוי אישי."""

    def __init__(self, db_manager):
        """
        Args:
            db_manager: מופע של DatabaseManager (database/manager.py)
        """
        self.db = db_manager

    # ================================================================
    #  ייצוא
    # ================================================================
    def export_user_data(self, user_id: int) -> BytesIO:
        """
        יוצר קובץ ZIP עם כל המידע של המשתמש.

        Returns:
            BytesIO buffer מוכן לשליחה כ-response
        """
        buffer = BytesIO()

        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            # 1) קבצי קוד רגילים + מטאדאטה
            files_meta = self._export_regular_files(zf, user_id)

            # 2) קבצים גדולים + מטאדאטה
            large_files_meta = self._export_large_files(zf, user_id)

            # 3) מטאדאטה מלאה של כל הקבצים (כולל tags, favorites, pinned)
            all_meta = {"regular_files": files_meta, "large_files": large_files_meta}
            zf.writestr("metadata/files.json", _to_json(all_meta))

            # 4) אוספים
            collections_data = self._export_collections(user_id)
            zf.writestr("metadata/collections.json", _to_json(collections_data))

            # 5) סימניות
            bookmarks_data = self._export_bookmarks(user_id)
            zf.writestr("metadata/bookmarks.json", _to_json(bookmarks_data))

            # 6) פתקיות
            notes_data = self._export_sticky_notes(user_id)
            zf.writestr("metadata/sticky_notes.json", _to_json(notes_data))

            # 7) העדפות משתמש
            prefs_data = self._export_preferences(user_id)
            zf.writestr("metadata/preferences.json", _to_json(prefs_data))

            # 8) העדפות Drive
            drive_data = self._export_drive_prefs(user_id)
            zf.writestr("metadata/drive_prefs.json", _to_json(drive_data))

            # 9) מטאדאטה של הגיבוי עצמו
            backup_info = {
                "version": BACKUP_FORMAT_VERSION,
                "user_id": user_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "files_count": len(files_meta),
                "large_files_count": len(large_files_meta),
                "collections_count": len(collections_data.get("collections", [])),
                "bookmarks_count": len(bookmarks_data),
                "notes_count": len(notes_data),
            }
            zf.writestr("backup_info.json", _to_json(backup_info))

        buffer.seek(0)
        emit_event(
            "personal_backup_export",
            user_id=user_id,
            files_count=len(files_meta),
            large_files_count=len(large_files_meta),
        )
        return buffer

    def _export_regular_files(self, zf: zipfile.ZipFile, user_id: int) -> List[Dict]:
        """מייצא את כל קבצי הקוד הרגילים — תוכן + מטאדאטה."""
        meta_list = []
        try:
            # שליפה ללא projection כדי לקבל מטאדאטה מלאה (אבל בלי code עצמו ברשימה)
            files = self.db.get_user_files(user_id, limit=10000)
        except Exception as e:
            logger.error(f"שגיאה בשליפת קבצים לייצוא: {e}")
            return meta_list

        for file_doc in files:
            file_name = file_doc.get("file_name", "")
            if not file_name:
                continue

            # שליפת תוכן מלא
            try:
                full_doc = self.db.get_file(user_id, file_name)
            except Exception:
                full_doc = None

            code = ""
            if full_doc and isinstance(full_doc, dict):
                code = full_doc.get("code", "") or ""

            # כתיבת התוכן ל-ZIP
            safe_name = _safe_zip_path(f"files/{file_name}")
            try:
                zf.writestr(safe_name, code)
            except Exception as e:
                logger.warning(f"לא ניתן לכתוב {file_name} ל-ZIP: {e}")
                continue

            # מטאדאטה (ללא התוכן עצמו)
            meta = {
                "file_name": file_name,
                "programming_language": file_doc.get("programming_language", ""),
                "description": file_doc.get("description", ""),
                "tags": list(file_doc.get("tags") or []),
                "is_favorite": bool(file_doc.get("is_favorite", False)),
                "is_pinned": bool(file_doc.get("is_pinned", False)),
                "pin_order": file_doc.get("pin_order", 0),
                "version": file_doc.get("version", 1),
                "created_at": _dt_to_str(file_doc.get("created_at")),
                "updated_at": _dt_to_str(file_doc.get("updated_at")),
            }
            meta_list.append(meta)

        return meta_list

    def _export_large_files(self, zf: zipfile.ZipFile, user_id: int) -> List[Dict]:
        """מייצא את כל הקבצים הגדולים — תוכן + מטאדאטה."""
        meta_list = []
        try:
            large_files, _ = self.db.get_user_large_files(user_id, page=1, per_page=10000)
        except Exception as e:
            logger.error(f"שגיאה בשליפת קבצים גדולים לייצוא: {e}")
            return meta_list

        for file_doc in large_files:
            file_name = file_doc.get("file_name", "")
            if not file_name:
                continue

            # שליפת תוכן מלא
            try:
                full_doc = self.db.get_large_file(user_id, file_name)
            except Exception:
                full_doc = None

            content = ""
            if full_doc and isinstance(full_doc, dict):
                content = full_doc.get("content", "") or ""

            safe_name = _safe_zip_path(f"large_files/{file_name}")
            try:
                zf.writestr(safe_name, content)
            except Exception as e:
                logger.warning(f"לא ניתן לכתוב {file_name} ל-ZIP: {e}")
                continue

            meta = {
                "file_name": file_name,
                "programming_language": file_doc.get("programming_language", ""),
                "description": file_doc.get("description", ""),
                "tags": list(file_doc.get("tags") or []),
                "file_size": file_doc.get("file_size", 0),
                "lines_count": file_doc.get("lines_count", 0),
                "created_at": _dt_to_str(file_doc.get("created_at")),
                "updated_at": _dt_to_str(file_doc.get("updated_at")),
            }
            meta_list.append(meta)

        return meta_list

    def _export_collections(self, user_id: int) -> Dict[str, Any]:
        """מייצא אוספים + הפריטים שלהם."""
        try:
            from database.collections_manager import CollectionsManager

            raw_db = getattr(self.db, "db", None)
            if raw_db is None:
                return {"collections": [], "items": []}
            mgr = CollectionsManager(raw_db)
            result = mgr.list_collections(user_id, limit=500)
            collections = result.get("collections", []) if result.get("ok") else []

            all_items = []
            for coll in collections:
                cid = coll.get("id")
                if not cid:
                    continue
                items_res = mgr.get_collection_items(user_id, cid, page=1, per_page=5000, fetch_all=True)
                if items_res.get("ok"):
                    for item in items_res.get("items", []):
                        item["_collection_id"] = cid
                        all_items.append(item)

            return {"collections": collections, "items": all_items}
        except Exception as e:
            logger.error(f"שגיאה בייצוא אוספים: {e}")
            return {"collections": [], "items": []}

    def _export_bookmarks(self, user_id: int) -> List[Dict]:
        """מייצא סימניות.

        get_user_bookmarks מחזיר מבנה מקובץ לפי קבצים:
        {"files": [{"file_id", "file_name", "file_path", "bookmarks": [...]}]}

        אנחנו משטחים את המבנה לרשימה אחת שקל לשחזר אותה.
        """
        try:
            raw_db = getattr(self.db, "db", None)
            if raw_db is None:
                return []
            # Prefer raw documents to preserve anchor-based bookmarks metadata.
            # The grouped API (`get_user_bookmarks`) does not include anchor_id/text/type,
            # so relying only on it would drop anchor bookmarks details.
            try:
                cur = raw_db.file_bookmarks.find(
                    {"user_id": int(user_id), "valid": {"$ne": False}},
                    {"_id": 0},
                )
                # attempt to sort/limit on cursor; fall back to slicing list in stubs
                try:
                    cur = cur.sort([("created_at", -1)])
                except Exception:
                    pass
                try:
                    cur = cur.limit(int(BOOKMARKS_EXPORT_LIMIT))
                except Exception:
                    pass
                raw_docs = list(cur) if not isinstance(cur, list) else list(cur)[: int(BOOKMARKS_EXPORT_LIMIT)]
                out: List[Dict[str, Any]] = []
                for d in raw_docs:
                    if not isinstance(d, dict):
                        continue
                    file_name = str(d.get("file_name") or "")
                    if not file_name:
                        continue
                    try:
                        line_number = int(d.get("line_number") or 1)
                    except Exception:
                        line_number = 1
                    anchor_id_val = d.get("anchor_id")
                    anchor_id_str = (
                        str(anchor_id_val).strip()
                        if isinstance(anchor_id_val, str) and str(anchor_id_val).strip()
                        else ""
                    )
                    out.append(
                        {
                            "file_name": file_name,
                            "file_path": str(d.get("file_path") or file_name),
                            "line_number": line_number,
                            "line_text_preview": str(d.get("line_text_preview") or ""),
                            "note": str(d.get("note") or ""),
                            "color": str(d.get("color") or "yellow"),
                            "created_at": _dt_to_str(d.get("created_at")),
                        }
                    )
                    # הוסף שדות עוגן רק כאשר קיים anchor_id ממשי (לא ריק)
                    if anchor_id_str:
                        out[-1]["anchor_id"] = anchor_id_str
                        if d.get("anchor_text"):
                            out[-1]["anchor_text"] = d.get("anchor_text")
                        if d.get("anchor_type"):
                            out[-1]["anchor_type"] = d.get("anchor_type")
                return out
            except Exception:
                # Fallback to grouped API (may miss anchor metadata)
                from database.bookmarks_manager import BookmarksManager

                mgr = BookmarksManager(raw_db)
                result = mgr.get_user_bookmarks(user_id, limit=5000)
                if not result.get("ok"):
                    return []
                flat_bookmarks: List[Dict[str, Any]] = []
                for file_group in result.get("files", []):
                    file_name = file_group.get("file_name", "")
                    file_path = file_group.get("file_path", "")
                    for bm in file_group.get("bookmarks", []):
                        flat_bookmarks.append(
                            {
                                "file_name": file_name,
                                "file_path": file_path,
                                "line_number": bm.get("line_number", 1),
                                "line_text_preview": bm.get("line_text_preview", "") or "",
                                "note": bm.get("note", ""),
                                "color": bm.get("color", "yellow"),
                                "anchor_id": bm.get("anchor_id"),
                                "anchor_text": bm.get("anchor_text"),
                                "anchor_type": bm.get("anchor_type"),
                                "created_at": _dt_to_str(bm.get("created_at")),
                            }
                        )
                return flat_bookmarks
        except Exception as e:
            logger.error(f"שגיאה בייצוא סימניות: {e}")
            return []

    def _export_sticky_notes(self, user_id: int) -> List[Dict]:
        """מייצא פתקיות.

        חשוב: שומרים file_name ו-scope_id (לא רק file_id) כדי שנוכל
        לעשות resolve בשחזור — כי file_id (ObjectId) ישתנה.
        """
        try:
            raw_db = getattr(self.db, "db", None)
            if raw_db is None:
                return []
            cur = raw_db.sticky_notes.find(
                {"user_id": int(user_id)},
                {"_id": 0},  # ללא ObjectId שלא ניתן לסריאליזציה
            )
            try:
                cur = cur.sort([("updated_at", -1)])
            except Exception:
                pass
            try:
                cur = cur.limit(int(STICKY_NOTES_EXPORT_LIMIT))
            except Exception:
                pass
            notes = list(cur) if not isinstance(cur, list) else list(cur)[: int(STICKY_NOTES_EXPORT_LIMIT)]
            # המרת datetime ל-string
            for note in notes:
                for key in ("created_at", "updated_at", "remind_at"):
                    if key in note and isinstance(note[key], datetime):
                        note[key] = note[key].isoformat()
                # ודא ש-file_name קיים — הוא הכרחי לשחזור
                if "file_name" not in note and "file_id" in note:
                    try:
                        file_id = note["file_id"]
                        doc = raw_db.code_snippets.find_one(
                            {"_id": file_id, "user_id": int(user_id)},
                            {"file_name": 1},
                        )
                        if doc and isinstance(doc, dict):
                            note["file_name"] = doc.get("file_name", "")
                    except Exception:
                        pass
            return notes
        except Exception as e:
            logger.error(f"שגיאה בייצוא פתקיות: {e}")
            return []

    def _export_preferences(self, user_id: int) -> Dict[str, Any]:
        """מייצא העדפות משתמש."""
        try:
            raw_db = getattr(self.db, "db", None)
            if raw_db is None:
                return {}
            doc = raw_db.user_preferences.find_one({"user_id": user_id}, {"_id": 0})
            if not doc or not isinstance(doc, dict):
                return {}
            # המרת datetime
            for key, val in doc.items():
                if isinstance(val, datetime):
                    doc[key] = val.isoformat()
            return doc
        except Exception as e:
            logger.error(f"שגיאה בייצוא העדפות: {e}")
            return {}

    def _export_drive_prefs(self, user_id: int) -> Dict[str, Any]:
        """מייצא העדפות Drive."""
        try:
            prefs = self.db.get_drive_prefs(user_id)
            return prefs if isinstance(prefs, dict) else {}
        except Exception:
            return {}

    # ================================================================
    #  שחזור
    # ================================================================
    def restore_user_data(
        self,
        user_id: int,
        zip_bytes: bytes,
        *,
        overwrite: bool = False,
    ) -> Dict[str, Any]:
        """
        משחזר נתוני משתמש מקובץ ZIP.

        Args:
            user_id: מזהה המשתמש המשחזר
            zip_bytes: תוכן קובץ ה-ZIP
            overwrite: אם True, יוצר גרסה חדשה לקבצים קיימים (ההיסטוריה נשמרת)

        Returns:
            dict עם סיכום: {"ok": bool, "restored": {...}, "errors": [...]}
        """
        if len(zip_bytes) > MAX_RESTORE_ZIP_SIZE:
            return {
                "ok": False,
                "error": f"קובץ גדול מדי (מקסימום {MAX_RESTORE_ZIP_SIZE // (1024*1024)}MB)",
            }

        errors: List[str] = []
        restored = {
            "files": 0,
            "large_files": 0,
            "collections": 0,
            "collection_items": 0,
            "bookmarks": 0,
            "sticky_notes": 0,
            "preferences": False,
            "drive_prefs": False,
        }

        try:
            zf = zipfile.ZipFile(BytesIO(zip_bytes), "r")
        except zipfile.BadZipFile:
            return {"ok": False, "error": "קובץ ZIP לא תקין"}

        with zf:
            # הגנה מפני zip bomb — בדיקת גודל לא-דחוס מצטבר (best-effort לפי header)
            # בנוסף, כל קריאה בפועל מה-ZIP מוגבלת בגודל וב-budget מצטבר (ראה _ZipReadBudget).
            total_uncompressed = sum(info.file_size for info in zf.infolist())
            if total_uncompressed > MAX_UNCOMPRESSED_SIZE:
                return {
                    "ok": False,
                    "error": (
                        f"גודל לא-דחוס ({total_uncompressed // (1024*1024)}MB) "
                        f"חורג מהמקסימום ({MAX_UNCOMPRESSED_SIZE // (1024*1024)}MB)"
                    ),
                }

            # בדיקת קובץ בודד חריג (best-effort לפי header)
            for info in zf.infolist():
                if info.file_size > MAX_SINGLE_FILE_SIZE:
                    return {
                        "ok": False,
                        "error": (
                            f"הקובץ {info.filename} גדול מדי "
                            f"({info.file_size // (1024*1024)}MB, מקסימום {MAX_SINGLE_FILE_SIZE // (1024*1024)}MB)"
                        ),
                    }

            # Budget מצטבר לפי bytes לא-דחוסים שנקראים בפועל
            budget = _ZipReadBudget(MAX_UNCOMPRESSED_SIZE)

            # בדיקת גרסה
            try:
                info_raw = _read_zip_member_bytes_limited(
                    zf, "backup_info.json", max_bytes=MAX_SINGLE_FILE_SIZE, budget=budget
                )
                backup_info = json.loads(info_raw)
                version = backup_info.get("version", 0)
                if version > BACKUP_FORMAT_VERSION:
                    return {
                        "ok": False,
                        "error": f"גרסת גיבוי {version} לא נתמכת (נתמכת: {BACKUP_FORMAT_VERSION})",
                    }
            except KeyError:
                # אין backup_info — נמשיך בזהירות
                backup_info = {}
            except Exception as e:
                try:
                    logger.exception("שגיאה בקריאת backup_info", exc_info=True)
                except Exception:
                    pass
                errors.append("שגיאה בקריאת backup_info")
                backup_info = {}

            # 1) שחזור קבצים רגילים
            files_meta = self._read_json_from_zip(zf, "metadata/files.json", errors, budget=budget)
            regular_meta = (
                files_meta.get("regular_files", []) if isinstance(files_meta, dict) else []
            )
            restored["files"] = self._restore_regular_files(
                zf, user_id, regular_meta, overwrite, errors, budget=budget
            )

            # 2) שחזור קבצים גדולים
            large_meta = (
                files_meta.get("large_files", []) if isinstance(files_meta, dict) else []
            )
            restored["large_files"] = self._restore_large_files(
                zf, user_id, large_meta, overwrite, errors, budget=budget
            )

            # 3) שחזור אוספים
            collections_data = self._read_json_from_zip(
                zf, "metadata/collections.json", errors, budget=budget
            )
            if isinstance(collections_data, dict):
                c, ci = self._restore_collections(user_id, collections_data, errors)
                restored["collections"] = c
                restored["collection_items"] = ci

            # 4) שחזור סימניות
            bookmarks_data = self._read_json_from_zip(zf, "metadata/bookmarks.json", errors, budget=budget)
            if isinstance(bookmarks_data, list):
                restored["bookmarks"] = self._restore_bookmarks(user_id, bookmarks_data, errors)

            # 5) שחזור פתקיות
            notes_data = self._read_json_from_zip(
                zf, "metadata/sticky_notes.json", errors, budget=budget
            )
            if isinstance(notes_data, list):
                restored["sticky_notes"] = self._restore_sticky_notes(
                    user_id, notes_data, errors
                )

            # 6) שחזור העדפות
            prefs_data = self._read_json_from_zip(
                zf, "metadata/preferences.json", errors, budget=budget
            )
            if isinstance(prefs_data, dict) and prefs_data:
                restored["preferences"] = self._restore_preferences(user_id, prefs_data, errors)

            # 7) שחזור העדפות Drive
            drive_data = self._read_json_from_zip(zf, "metadata/drive_prefs.json", errors, budget=budget)
            if isinstance(drive_data, dict) and drive_data:
                restored["drive_prefs"] = self._restore_drive_prefs(user_id, drive_data, errors)

        emit_event(
            "personal_backup_restore",
            user_id=user_id,
            restored_files=restored["files"],
            restored_large=restored["large_files"],
            errors_count=len(errors),
        )

        return {"ok": True, "restored": restored, "errors": errors}

    def _restore_regular_files(
        self,
        zf: zipfile.ZipFile,
        user_id: int,
        meta_list: List[Dict],
        overwrite: bool,
        errors: List[str],
        *,
        budget: "_ZipReadBudget",
    ) -> int:
        """משחזר קבצי קוד רגילים.

        הערה חשובה לגבי overwrite:
        save_code_snippet תמיד עושה insert_one (גרסה חדשה) — זו מערכת versioning.
        - overwrite=False: מדלג על קבצים שכבר קיימים.
        - overwrite=True: יוצר גרסה חדשה (version N+1) של הקובץ הקיים,
          כך שהתוכן מהגיבוי הופך לגרסה האחרונה, אבל ההיסטוריה נשמרת.
        """
        from database.models import CodeSnippet

        count = 0
        for meta in meta_list:
            file_name = meta.get("file_name", "")
            if not file_name:
                continue

            # בדיקת קיום
            existing = self.db.get_file(user_id, file_name)
            if existing and not overwrite:
                continue

            desired_is_favorite = bool(meta.get("is_favorite", False))
            desired_is_pinned = bool(meta.get("is_pinned", False))
            try:
                desired_pin_order = int(meta.get("pin_order", 0) or 0)
            except Exception:
                desired_pin_order = 0

            # קריאת תוכן מה-ZIP *לפני* פעולות כתיבה, כדי למנוע partial-update אם הקריאה נכשלת
            zip_path = _safe_zip_path(f"files/{file_name}")
            try:
                code_bytes = _read_zip_member_bytes_limited(
                    zf, zip_path, max_bytes=MAX_SINGLE_FILE_SIZE, budget=budget
                )
                code = code_bytes.decode("utf-8", errors="replace")
            except KeyError:
                errors.append(f"קובץ חסר ב-ZIP: {zip_path}")
                continue
            except Exception as e:
                try:
                    logger.exception("שגיאה בקריאת קובץ מהגיבוי: %s", zip_path, exc_info=True)
                except Exception:
                    pass
                errors.append(f"שגיאה בקריאת קובץ מהגיבוי: {zip_path}")
                continue

            # חשוב: כש-overwrite=True, ניישר מועדפים/נעיצה רק אחרי שהצלחנו לקרוא מה-ZIP
            # כדי למנוע שינוי מצב קיים כאשר שחזור התוכן נכשל.
            if existing and overwrite:
                # Favorites: set desired state using toggle (updates all versions)
                try:
                    current_fav = bool(self.db.is_favorite(user_id, file_name))
                    if current_fav != desired_is_favorite:
                        new_state = self.db.toggle_favorite(user_id, file_name)
                        if new_state is None:
                            errors.append(f"לא ניתן לעדכן מצב מועדפים עבור {file_name}")
                except Exception:
                    try:
                        logger.exception(
                            "שגיאה בעדכון מצב מועדפים בשחזור: %s", file_name, exc_info=True
                        )
                    except Exception:
                        pass
                    errors.append(f"שגיאה בעדכון מצב מועדפים עבור {file_name}")

                # Pinned: set desired state using toggle (updates all versions)
                try:
                    current_pinned = bool(self.db.is_pinned(user_id, file_name))
                    if current_pinned != desired_is_pinned:
                        out = self.db.toggle_pin(user_id, file_name)
                        if not isinstance(out, dict) or not bool(out.get("success", False)):
                            errors.append(f"לא ניתן לעדכן מצב נעיצה עבור {file_name}")
                except Exception:
                    try:
                        logger.exception("שגיאה בעדכון מצב נעיצה בשחזור: %s", file_name, exc_info=True)
                    except Exception:
                        pass
                    errors.append(f"שגיאה בעדכון מצב נעיצה עבור {file_name}")

                # Enforce pin order when pinned (even if content is identical and we skip saving)
                if desired_is_pinned:
                    try:
                        ok = self.db.reorder_pinned(user_id, file_name, desired_pin_order)
                        if ok is False:
                            errors.append(f"לא ניתן לעדכן סדר נעיצה עבור {file_name}")
                    except Exception:
                        try:
                            logger.exception("שגיאה בעדכון סדר נעיצה בשחזור: %s", file_name, exc_info=True)
                        except Exception:
                            pass
                        errors.append(f"שגיאה בעדכון סדר נעיצה עבור {file_name}")

            # דלג אם התוכן זהה לגרסה הקיימת (מונע גרסאות כפולות מיותרות)
            if existing and overwrite:
                existing_code = existing.get("code", "")
                if existing_code == code:
                    # אם התוכן זהה אבל מטאדאטה שונה (שפה/תיאור/תגיות) —
                    # עדיין ניצור גרסה חדשה כדי לעדכן את המטאדאטה לפי הגיבוי.
                    if _metadata_equivalent(existing, meta, default_lang="text"):
                        continue

            # שמירה — save_code_snippet ימצא גרסה קיימת ויעלה version אוטומטית
            try:
                snippet = CodeSnippet(
                    user_id=user_id,
                    file_name=file_name,
                    code=code,
                    programming_language=_restore_programming_language(meta, default_lang="text"),
                    description=str(meta.get("description", "") or ""),
                    tags=list(meta.get("tags") or []),
                    is_favorite=desired_is_favorite,
                    is_pinned=desired_is_pinned,
                    pin_order=desired_pin_order,
                )
                self.db.save_code_snippet(snippet)
                count += 1
            except Exception as e:
                try:
                    logger.exception("שגיאה בשמירת קובץ משוחזר: %s", file_name, exc_info=True)
                except Exception:
                    pass
                errors.append(f"שגיאה בשמירת {file_name}")

        return count

    def _restore_large_files(
        self,
        zf: zipfile.ZipFile,
        user_id: int,
        meta_list: List[Dict],
        overwrite: bool,
        errors: List[str],
        *,
        budget: "_ZipReadBudget",
    ) -> int:
        """משחזר קבצים גדולים.

        הערה: save_large_file עושה delete + insert (upsert אמיתי),
        כך שב-overwrite=True הקובץ הקיים יוחלף בתוכן מהגיבוי.
        כדי להימנע מהחלפה מיותרת, בודקים אם התוכן זהה.
        """
        from database.models import LargeFile

        count = 0
        for meta in meta_list:
            file_name = meta.get("file_name", "")
            if not file_name:
                continue

            existing = self.db.get_large_file(user_id, file_name)
            if existing and not overwrite:
                continue

            zip_path = _safe_zip_path(f"large_files/{file_name}")
            try:
                content_bytes = _read_zip_member_bytes_limited(
                    zf, zip_path, max_bytes=MAX_SINGLE_FILE_SIZE, budget=budget
                )
                content = content_bytes.decode("utf-8", errors="replace")
            except KeyError:
                errors.append(f"קובץ גדול חסר ב-ZIP: {zip_path}")
                continue
            except Exception as e:
                try:
                    logger.exception("שגיאה בקריאת קובץ גדול מהגיבוי: %s", zip_path, exc_info=True)
                except Exception:
                    pass
                errors.append(f"שגיאה בקריאת קובץ גדול מהגיבוי: {zip_path}")
                continue

            # דלג אם התוכן זהה (מונע delete + insert מיותרים)
            if existing and overwrite:
                existing_content = existing.get("content", "")
                if existing_content == content:
                    if _metadata_equivalent(existing, meta, default_lang="text"):
                        continue

            try:
                large_file = LargeFile(
                    user_id=user_id,
                    file_name=file_name,
                    content=content,
                    programming_language=_restore_programming_language(meta, default_lang="text"),
                    file_size=len(content.encode("utf-8")),
                    lines_count=len(content.split("\n")),
                    description=meta.get("description", ""),
                    tags=list(meta.get("tags") or []),
                )
                self.db.save_large_file(large_file)
                count += 1
            except Exception as e:
                try:
                    logger.exception("שגיאה בשמירת קובץ גדול משוחזר: %s", file_name, exc_info=True)
                except Exception:
                    pass
                errors.append(f"שגיאה בשמירת קובץ גדול {file_name}")

        return count

    def _restore_collections(
        self,
        user_id: int,
        data: Dict[str, Any],
        errors: List[str],
    ) -> tuple:
        """משחזר אוספים ופריטים.

        בדיקת כפילות: אם אוסף עם אותו שם כבר קיים, ממפים את ה-ID הישן
        לאוסף הקיים ומדלגים על היצירה — כך שחזור חוזר לא יוצר כפילויות.
        """
        collections_count = 0
        items_count = 0

        try:
            from database.collections_manager import CollectionsManager

            raw_db = getattr(self.db, "db", None)
            if raw_db is None:
                return 0, 0
            mgr = CollectionsManager(raw_db)
        except Exception as e:
            try:
                logger.exception("שגיאה באתחול CollectionsManager", exc_info=True)
            except Exception:
                pass
            errors.append("שגיאה באתחול CollectionsManager")
            return 0, 0

        # טען אוספים קיימים לבדיקת כפילות לפי שם
        existing_collections = {}
        try:
            existing_result = mgr.list_collections(user_id, limit=500)
            if existing_result.get("ok"):
                for ec in existing_result.get("collections", []):
                    name = (ec.get("name") or "").strip()
                    if name:
                        existing_collections[name] = ec.get("id", "")
        except Exception:
            pass

        old_to_new_id = {}  # מיפוי ID ישן → חדש

        for coll in data.get("collections", []):
            try:
                old_id = coll.get("id", "")
                coll_name = (coll.get("name") or "אוסף משוחזר").strip()

                # בדיקת כפילות — אם אוסף עם אותו שם כבר קיים, מפה ודלג
                if coll_name in existing_collections:
                    existing_id = existing_collections[coll_name]
                    if old_id and existing_id:
                        old_to_new_id[old_id] = existing_id
                    continue

                result = mgr.create_collection(
                    user_id=user_id,
                    name=coll_name,
                    description=coll.get("description", ""),
                    mode=coll.get("mode", "manual"),
                    icon=coll.get("icon"),
                    color=coll.get("color"),
                    is_favorite=coll.get("is_favorite", False),
                )
                if result.get("ok") and result.get("collection"):
                    new_id = result["collection"].get("id")
                    if old_id and new_id:
                        old_to_new_id[old_id] = new_id
                    collections_count += 1
            except Exception as e:
                try:
                    logger.exception("שגיאה ביצירת אוסף בשחזור", exc_info=True)
                except Exception:
                    pass
                errors.append(f"שגיאה ביצירת אוסף '{coll.get('name', '')}'")

        # שחזור פריטים
        items_by_collection: Dict[str, List[Dict]] = {}
        for item in data.get("items", []):
            old_cid = item.get("_collection_id") or item.get("collection_id", "")
            new_cid = old_to_new_id.get(old_cid)
            if not new_cid:
                continue
            items_by_collection.setdefault(new_cid, []).append(item)

        for new_cid, items in items_by_collection.items():
            try:
                add_items = [
                    {
                        "source": it.get("source", "regular"),
                        "file_name": it.get("file_name", ""),
                        "note": it.get("note", ""),
                    }
                    for it in items
                    if it.get("file_name")
                ]
                if add_items:
                    result = mgr.add_items(user_id, new_cid, add_items)
                    items_count += result.get("added", 0)
            except Exception as e:
                try:
                    logger.exception("שגיאה בהוספת פריטים לאוסף בשחזור", exc_info=True)
                except Exception:
                    pass
                errors.append("שגיאה בהוספת פריטים לאוסף")

        return collections_count, items_count

    def _restore_bookmarks(self, user_id: int, bookmarks: List[Dict], errors: List[str]) -> int:
        """משחזר סימניות (best-effort).

        חשוב:
        - לא משתמשים ב-toggle_bookmark כי הוא מוחק סימניה קיימת באותו מיקום.
        - במקום זה, עושים insert ישיר לקולקציה (אחרי בדיקת כפילות).
        - toggle_bookmark גם דורש file_name ו-file_path כפרמטרים חובה.
        """
        count = 0
        try:
            raw_db = getattr(self.db, "db", None)
            if raw_db is None:
                return 0

            for bm in bookmarks:
                try:
                    file_name = bm.get("file_name", "")
                    if not file_name:
                        continue
                    # מצא את הקובץ המשוחזר כדי לקבל file_id חדש
                    file_doc = self.db.get_file(user_id, file_name)
                    if not file_doc:
                        continue
                    file_id = str(file_doc.get("_id", ""))
                    if not file_id:
                        continue

                    line_number = bm.get("line_number", 1)
                    anchor_id = bm.get("anchor_id")
                    anchor_id_str = (
                        str(anchor_id).strip()
                        if isinstance(anchor_id, str) and str(anchor_id).strip()
                        else ""
                    )

                    # בדיקת כפילות — לפי anchor_id אם קיים, אחרת לפי line_number
                    if anchor_id_str:
                        existing = raw_db.file_bookmarks.find_one(
                            {"user_id": user_id, "file_id": file_id, "anchor_id": anchor_id_str}
                        )
                    else:
                        existing = raw_db.file_bookmarks.find_one(
                            {"user_id": user_id, "file_id": file_id, "line_number": line_number}
                        )
                    if existing:
                        continue

                    # insert ישיר (לא toggle!) כדי לא למחוק סימניות קיימות
                    doc = {
                        "user_id": user_id,
                        "file_id": file_id,
                        "file_name": file_name,
                        "file_path": bm.get("file_path", file_name),
                        "line_number": line_number,
                        "line_text_preview": (bm.get("line_text_preview") or bm.get("line_text", "") or "")[:100],
                        "note": bm.get("note", ""),
                        "color": bm.get("color", "yellow"),
                        "valid": True,
                        "sync_status": "synced",
                        "sync_confidence": 1.0,
                        "created_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    }
                    # הוסף שדות עוגן רק כאשר קיים anchor_id ממשי (לא ריק)
                    if anchor_id_str:
                        doc["anchor_id"] = anchor_id_str
                        if bm.get("anchor_text"):
                            doc["anchor_text"] = bm.get("anchor_text")
                        if bm.get("anchor_type"):
                            doc["anchor_type"] = bm.get("anchor_type")
                    raw_db.file_bookmarks.insert_one(doc)
                    count += 1
                except Exception:
                    continue
        except Exception as e:
            try:
                logger.exception("שגיאה בשחזור סימניות", exc_info=True)
            except Exception:
                pass
            errors.append("שגיאה בשחזור סימניות")

        return count

    def _restore_sticky_notes(self, user_id: int, notes: List[Dict], errors: List[str]) -> int:
        """משחזר פתקיות (best-effort).

        חשוב: ה-file_id מהגיבוי הוא ObjectId ישן שכבר לא תקף.
        חייבים לעשות resolve לפי file_name כדי לקבל את ה-file_id החדש,
        וגם לחשב scope_id חדש (כמו ב-sticky_notes_api._resolve_scope).
        """
        count = 0
        try:
            raw_db = getattr(self.db, "db", None)
            if raw_db is None:
                return 0
            for note in notes:
                try:
                    # resolve file_id חדש לפי file_name
                    file_name = note.get("file_name", "")
                    new_file_id = None

                    if not file_name:
                        continue  # לא ניתן לשייך את הפתקית בלי file_name

                    file_doc = None
                    try:
                        file_doc = self.db.get_file(user_id, file_name)
                    except Exception:
                        file_doc = None
                    if file_doc and isinstance(file_doc, dict):
                        new_file_id = str(file_doc.get("_id", ""))

                    # אם לא הצלחנו resolve לקובץ קיים — דלג כדי לא ליצור פתקיות יתומות
                    if not new_file_id:
                        errors.append(f"דילגתי על פתקית: הקובץ לא נמצא ({file_name})")
                        continue

                    # חישוב scope_id חדש — חייב להתאים ל-_make_scope_id בדיוק:
                    # שימוש בפונקציה קנונית כדי להימנע מסטיות עתידיות
                    from sticky_notes_scope import make_scope_id
                    scope_id = make_scope_id(int(user_id), file_name)

                    content = note.get("content", "")

                    # בדיקת כפילות — דלג אם כבר קיימת פתקית עם אותו תוכן ומיקום
                    dup_query = {"user_id": int(user_id), "content": content}
                    if scope_id:
                        dup_query["scope_id"] = scope_id
                    elif new_file_id:
                        dup_query["file_id"] = new_file_id
                    existing_note = raw_db.sticky_notes.find_one(dup_query)
                    if existing_note:
                        continue

                    doc = {
                        "user_id": int(user_id),
                        "file_id": new_file_id,
                        "file_name": file_name,
                        "scope_id": scope_id,
                        "content": content,
                        "color": note.get("color", "#FFFFCC"),
                        "position_x": note.get("position_x", 100),
                        "position_y": note.get("position_y", 100),
                        "width": note.get("width", 250),
                        "height": note.get("height", 200),
                        "is_minimized": bool(note.get("is_minimized", False)),
                        "line_start": note.get("line_start"),
                        "line_end": note.get("line_end"),
                        "anchor_id": note.get("anchor_id"),
                        "anchor_text": note.get("anchor_text"),
                        "created_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    }
                    raw_db.sticky_notes.insert_one(doc)
                    count += 1
                except Exception:
                    continue
        except Exception as e:
            try:
                logger.exception("שגיאה בשחזור פתקיות", exc_info=True)
            except Exception:
                pass
            errors.append("שגיאה בשחזור פתקיות")

        return count

    def _restore_preferences(self, user_id: int, prefs: Dict[str, Any], errors: List[str]) -> bool:
        """משחזר העדפות משתמש."""
        try:
            raw_db = getattr(self.db, "db", None)
            if raw_db is None:
                return False
            # הסר שדות שלא צריך לדרוס
            prefs.pop("_id", None)
            prefs.pop("user_id", None)
            updates = _sanitize_user_preferences(prefs)
            if not updates:
                return False
            raw_db.user_preferences.update_one({"user_id": user_id}, {"$set": updates}, upsert=True)
            return True
        except Exception as e:
            try:
                logger.exception("שגיאה בשחזור העדפות", exc_info=True)
            except Exception:
                pass
            errors.append("שגיאה בשחזור העדפות")
            return False

    def _restore_drive_prefs(self, user_id: int, prefs: Dict[str, Any], errors: List[str]) -> bool:
        """משחזר העדפות Drive.

        משתמש ב-save_drive_prefs שעושה merge עם הקיים (לא דריסה מלאה).
        """
        try:
            if not prefs:
                return False
            return self.db.save_drive_prefs(user_id, prefs)
        except Exception as e:
            try:
                logger.exception("שגיאה בשחזור העדפות Drive", exc_info=True)
            except Exception:
                pass
            errors.append("שגיאה בשחזור העדפות Drive")
            return False

    # ================================================================
    #  עזרים
    # ================================================================
    @staticmethod
    def _read_json_from_zip(
        zf: zipfile.ZipFile,
        path: str,
        errors: List[str],
        *,
        budget: "_ZipReadBudget",
    ) -> Any:
        """קורא וממיר קובץ JSON מתוך ה-ZIP."""
        try:
            raw = _read_zip_member_bytes_limited(
                zf, path, max_bytes=MAX_SINGLE_FILE_SIZE, budget=budget
            )
            return json.loads(raw)
        except KeyError:
            # קובץ לא קיים — לא שגיאה קריטית
            return None
        except Exception as e:
            try:
                logger.exception("שגיאה בקריאת JSON מהגיבוי: %s", path, exc_info=True)
            except Exception:
                pass
            errors.append(f"שגיאה בקריאת {path}")
            return None


# ==================== פונקציות עזר ====================


def _to_json(obj: Any) -> str:
    """המרה ל-JSON עם תמיכה ב-datetime ו-ObjectId.

    רשימה סגורה של טיפוסים מותרים — כל טיפוס לא מוכר יגרום ל-TypeError
    כדי לזהות נתונים פגומים מוקדם ולא לייצר גיבויים שקטים אבל שבורים.
    """
    # טיפוסים מוכרים שיש להמיר במפורש
    try:
        from bson import ObjectId as BsonObjectId

        _bson_types = (BsonObjectId,)
    except Exception:
        _bson_types = ()

    def _default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        if _bson_types and isinstance(o, _bson_types):
            return str(o)
        # bytes — הודעה ברורה
        if isinstance(o, bytes):
            raise TypeError(
                f"bytes object found in backup data (len={len(o)}). "
                "Ensure all content is decoded to str before export."
            )
        raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")

    return json.dumps(obj, ensure_ascii=False, indent=2, default=_default)


def _dt_to_str(dt) -> Optional[str]:
    """ממיר datetime למחרוזת ISO, או מחזיר None."""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def _safe_zip_path(path: str) -> str:
    """מנקה נתיב ZIP מתווים מסוכנים."""
    # מנע path traversal
    clean = path.replace("\\", "/")
    parts = [p for p in clean.split("/") if p and p != ".."]
    return "/".join(parts)


class _ZipReadBudget:
    """מונה bytes לא-דחוסים שנקראים בפועל (הגנה מפני zip bombs)."""

    def __init__(self, max_total_bytes: int) -> None:
        self.max_total_bytes = int(max_total_bytes or 0)
        self.total_bytes = 0

    def add(self, n: int) -> None:
        try:
            inc = int(n or 0)
        except Exception:
            inc = 0
        if inc <= 0:
            return
        self.total_bytes += inc
        if self.max_total_bytes > 0 and self.total_bytes > self.max_total_bytes:
            raise ValueError("חריגה ממגבלת גודל לא-דחוס בשחזור")


def _read_zip_member_bytes_limited(
    zf: zipfile.ZipFile,
    path: str,
    *,
    max_bytes: int,
    budget: _ZipReadBudget,
) -> bytes:
    """קריאה בטוחה של member מה-ZIP עם מגבלת גודל ובאדג'ט מצטבר.

    לא סומך על file_size מה-header (שיכול להיות שקרי), אלא סופר bytes בפועל בזמן קריאה.
    """
    safe_path = _safe_zip_path(path)
    max_b = int(max_bytes or 0)
    if max_b <= 0:
        raise ValueError("max_bytes לא תקין")

    out = bytearray()
    with zf.open(safe_path, "r") as fp:
        while True:
            chunk = fp.read(64 * 1024)
            if not chunk:
                break
            budget.add(len(chunk))
            out.extend(chunk)
            if len(out) > max_b:
                raise ValueError("קובץ גדול מדי בשחזור")
    return bytes(out)


def _metadata_equivalent(existing: Dict[str, Any], meta: Dict[str, Any], *, default_lang: str = "text") -> bool:
    """השוואת מטאדאטה בסיסית (שפה/תיאור/תגיות) כדי להחליט אם לדלג על כתיבה."""
    try:
        existing_lang = str(existing.get("programming_language", "") or "")
    except Exception:
        existing_lang = ""
    try:
        # שמור סימטריה: אם המפתח קיים במטאדאטה — אל תכפה default על מחרוזת ריקה.
        # זה מונע "שכתוב" מיותר כאשר גם בקיים וגם בגיבוי הערך ריק ("").
        if "programming_language" in meta:
            desired_lang = str(meta.get("programming_language") or "")
        else:
            desired_lang = str(default_lang)
    except Exception:
        desired_lang = str(default_lang)
    try:
        existing_desc = str(existing.get("description", "") or "")
    except Exception:
        existing_desc = ""
    try:
        desired_desc = str(meta.get("description", "") or "")
    except Exception:
        desired_desc = ""
    try:
        existing_tags = sorted(list(existing.get("tags") or []))
    except Exception:
        existing_tags = []
    try:
        desired_tags = sorted(list(meta.get("tags") or []))
    except Exception:
        desired_tags = []
    return existing_lang == desired_lang and existing_desc == desired_desc and existing_tags == desired_tags


def _restore_programming_language(meta: Dict[str, Any], *, default_lang: str = "text") -> str:
    """שחזור programming_language בצורה נאמנה לגיבוי.

    - אם המפתח קיים במטאדאטה, נשמר הערך כפי שהוא (כולל מחרוזת ריקה).
    - אם המפתח חסר (גיבוי ישן/חלקי), נשתמש ב-default.
    """
    try:
        if "programming_language" in meta:
            return str(meta.get("programming_language") or "")
        return str(default_lang)
    except Exception:
        return str(default_lang)


def _sanitize_user_preferences(prefs: Dict[str, Any]) -> Dict[str, Any]:
    """מסנן העדפות משתמש לפי allowlist כדי למנוע הזרקת שדות לא צפויים."""
    if not isinstance(prefs, dict) or not prefs:
        return {}

    updates: Dict[str, Any] = {}

    # attention_settings.* — מיושר ללוגיקה ב-settings_routes.py
    att = prefs.get("attention_settings")
    if isinstance(att, dict):
        allowed = USER_PREFERENCES_ALLOWLIST.get("attention_settings", set())
        for key in allowed:
            if key not in att:
                continue
            val = att.get(key)
            try:
                if key == "stale_days":
                    val = min(max(int(val), 7), 365)
                elif key == "max_items_per_group":
                    val = min(max(int(val), 3), 50)
                elif key in (
                    "enabled",
                    "show_missing_description",
                    "show_missing_tags",
                    "show_stale_files",
                ):
                    if isinstance(val, bool):
                        pass
                    elif isinstance(val, str):
                        if val.lower() in ("true", "1", "yes", "on"):
                            val = True
                        elif val.lower() in ("false", "0", "no", "off", ""):
                            val = False
                        else:
                            continue
                    else:
                        val = bool(val)
            except Exception:
                continue
            updates[f"attention_settings.{key}"] = val

    return updates

