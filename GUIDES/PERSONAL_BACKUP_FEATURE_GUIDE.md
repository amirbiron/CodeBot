# מדריך מימוש: גיבוי אישי בלחיצה (Personal Backup)

> כפתור בהגדרות שמייצר ZIP עם כל הקבצים, האוספים, התגיות וההגדרות של המשתמש — גיבוי מלא בקליק אחד. כולל אפשרות שחזור מ-ZIP.

---

## סקירה כללית

הפיצ'ר מוסיף לעמוד ההגדרות (`/settings`) שני כפתורים:
1. **ייצוא גיבוי** — יוצר קובץ ZIP שמכיל את כל המידע של המשתמש
2. **שחזור מגיבוי** — מעלה ZIP ומשחזר את כל המידע

### מה נכנס לגיבוי

| רכיב | מקור ב-DB | שם קובץ ב-ZIP |
|---|---|---|
| קבצי קוד (רגילים) | `code_snippets` | `files/<file_name>` |
| קבצים גדולים | `large_files` | `large_files/<file_name>` |
| מטאדאטה של קבצים | `code_snippets` + `large_files` | `metadata/files.json` |
| אוספים (collections) | `user_collections` | `metadata/collections.json` |
| פריטים באוספים | `collection_items` | `metadata/collection_items.json` |
| סימניות (bookmarks) | `file_bookmarks` | `metadata/bookmarks.json` |
| פתקיות (sticky notes) | `sticky_notes` | `metadata/sticky_notes.json` |
| העדפות משתמש | `user_preferences` | `metadata/preferences.json` |
| מועדפים + נעוצים | שדות ב-`code_snippets` | כלול ב-`metadata/files.json` |
| הגדרות Drive | שדה ב-`users` | `metadata/drive_prefs.json` |
| מידע גיבוי | — | `backup_info.json` |

---

## ארכיטקטורה

```
┌──────────────────────────────────────────────────────────┐
│                      Frontend                            │
├──────────────────────────────────────────────────────────┤
│  settings.html                                           │
│  ├─ כפתור "הורד גיבוי" → GET /api/backup/export         │
│  └─ כפתור "שחזר מגיבוי" → POST /api/backup/restore      │
│     └─ input[type=file] עם accept=".zip"                 │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│                      Backend                             │
├──────────────────────────────────────────────────────────┤
│  webapp/backup_api.py (Blueprint חדש)                    │
│  ├─ GET  /api/backup/export   → ייצוא ZIP               │
│  └─ POST /api/backup/restore  → שחזור מ-ZIP             │
│                                                          │
│  services/personal_backup_service.py (שירות חדש)         │
│  ├─ export_user_data(user_id) → BytesIO (ZIP)            │
│  └─ restore_user_data(user_id, zip_bytes) → dict         │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│                    Database Layer                         │
├──────────────────────────────────────────────────────────┤
│  DatabaseManager (database/manager.py)                   │
│  ├─ get_user_files()          — קבצים רגילים             │
│  ├─ get_user_large_files()    — קבצים גדולים             │
│  ├─ get_file() / get_large_file() — תוכן מלא            │
│  ├─ save_code_snippet()       — שמירת קובץ               │
│  ├─ save_large_file()         — שמירת קובץ גדול          │
│  └─ get_drive_prefs()         — העדפות Drive             │
│                                                          │
│  CollectionsManager (database/collections_manager.py)    │
│  ├─ list_collections()                                   │
│  ├─ get_collection_items()                               │
│  └─ create_collection() / add_items()                    │
│                                                          │
│  BookmarksManager (database/bookmarks_manager.py)        │
│  ├─ get_user_bookmarks()                                 │
│  └─ toggle_bookmark()                                    │
└──────────────────────────────────────────────────────────┘
```

---

## שלב 1: שירות הגיבוי — `services/personal_backup_service.py`

קובץ חדש שמרכז את כל הלוגיקה של ייצוא ושחזור.

```python
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
                items_res = mgr.get_collection_items(
                    user_id, cid, page=1, per_page=5000, fetch_all=True
                )
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
            from database.bookmarks_manager import BookmarksManager
            raw_db = getattr(self.db, "db", None)
            if raw_db is None:
                return []
            mgr = BookmarksManager(raw_db)
            result = mgr.get_user_bookmarks(user_id, limit=5000)
            if not result.get("ok"):
                return []

            # שטח את המבנה המקובץ לרשימה שטוחה
            flat_bookmarks = []
            for file_group in result.get("files", []):
                file_name = file_group.get("file_name", "")
                file_path = file_group.get("file_path", "")
                for bm in file_group.get("bookmarks", []):
                    flat_bookmarks.append({
                        "file_name": file_name,
                        "file_path": file_path,
                        "line_number": bm.get("line_number", 1),
                        "line_text": bm.get("line_text", ""),
                        "note": bm.get("note", ""),
                        "color": bm.get("color", "yellow"),
                        "created_at": _dt_to_str(bm.get("created_at")),
                    })
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
            notes = list(
                raw_db.sticky_notes.find(
                    {"user_id": int(user_id)},
                    {"_id": 0},  # ללא ObjectId שלא ניתן לסריאליזציה
                )
            )
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
            doc = raw_db.user_preferences.find_one(
                {"user_id": user_id}, {"_id": 0}
            )
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
            # הגנה מפני zip bomb — בדיקת גודל לא-דחוס מצטבר
            total_uncompressed = sum(info.file_size for info in zf.infolist())
            if total_uncompressed > MAX_UNCOMPRESSED_SIZE:
                return {
                    "ok": False,
                    "error": (
                        f"גודל לא-דחוס ({total_uncompressed // (1024*1024)}MB) "
                        f"חורג מהמקסימום ({MAX_UNCOMPRESSED_SIZE // (1024*1024)}MB)"
                    ),
                }

            # בדיקת קובץ בודד חריג
            for info in zf.infolist():
                if info.file_size > MAX_SINGLE_FILE_SIZE:
                    return {
                        "ok": False,
                        "error": (
                            f"הקובץ {info.filename} גדול מדי "
                            f"({info.file_size // (1024*1024)}MB, מקסימום {MAX_SINGLE_FILE_SIZE // (1024*1024)}MB)"
                        ),
                    }

            # בדיקת גרסה
            try:
                info_raw = zf.read("backup_info.json")
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
                errors.append(f"שגיאה בקריאת backup_info: {e}")
                backup_info = {}

            # 1) שחזור קבצים רגילים
            files_meta = self._read_json_from_zip(zf, "metadata/files.json", errors)
            regular_meta = files_meta.get("regular_files", []) if isinstance(files_meta, dict) else []
            restored["files"] = self._restore_regular_files(
                zf, user_id, regular_meta, overwrite, errors
            )

            # 2) שחזור קבצים גדולים
            large_meta = files_meta.get("large_files", []) if isinstance(files_meta, dict) else []
            restored["large_files"] = self._restore_large_files(
                zf, user_id, large_meta, overwrite, errors
            )

            # 3) שחזור אוספים
            collections_data = self._read_json_from_zip(zf, "metadata/collections.json", errors)
            if isinstance(collections_data, dict):
                c, ci = self._restore_collections(user_id, collections_data, errors)
                restored["collections"] = c
                restored["collection_items"] = ci

            # 4) שחזור סימניות
            bookmarks_data = self._read_json_from_zip(zf, "metadata/bookmarks.json", errors)
            if isinstance(bookmarks_data, list):
                restored["bookmarks"] = self._restore_bookmarks(user_id, bookmarks_data, errors)

            # 5) שחזור פתקיות
            notes_data = self._read_json_from_zip(zf, "metadata/sticky_notes.json", errors)
            if isinstance(notes_data, list):
                restored["sticky_notes"] = self._restore_sticky_notes(user_id, notes_data, errors)

            # 6) שחזור העדפות
            prefs_data = self._read_json_from_zip(zf, "metadata/preferences.json", errors)
            if isinstance(prefs_data, dict) and prefs_data:
                restored["preferences"] = self._restore_preferences(user_id, prefs_data, errors)

            # 7) שחזור העדפות Drive
            drive_data = self._read_json_from_zip(zf, "metadata/drive_prefs.json", errors)
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

            # אם overwrite=True וקובץ קיים — נבדוק אם התוכן זהה, ונדלג אם כן
            zip_path = _safe_zip_path(f"files/{file_name}")
            try:
                code = zf.read(zip_path).decode("utf-8", errors="replace")
            except KeyError:
                errors.append(f"קובץ חסר ב-ZIP: {zip_path}")
                continue
            except Exception as e:
                errors.append(f"שגיאה בקריאת {zip_path}: {e}")
                continue

            # דלג אם התוכן זהה לגרסה הקיימת (מונע גרסאות כפולות מיותרות)
            if existing and overwrite:
                existing_code = existing.get("code", "")
                if existing_code == code:
                    continue

            # שמירה — save_code_snippet ימצא גרסה קיימת ויעלה version אוטומטית
            try:
                snippet = CodeSnippet(
                    user_id=user_id,
                    file_name=file_name,
                    code=code,
                    programming_language=meta.get("programming_language", "text"),
                    description=meta.get("description", ""),
                    tags=list(meta.get("tags") or []),
                    is_favorite=bool(meta.get("is_favorite", False)),
                    is_pinned=bool(meta.get("is_pinned", False)),
                    pin_order=int(meta.get("pin_order", 0)),
                )
                self.db.save_code_snippet(snippet)
                count += 1
            except Exception as e:
                errors.append(f"שגיאה בשמירת {file_name}: {e}")

        return count

    def _restore_large_files(
        self,
        zf: zipfile.ZipFile,
        user_id: int,
        meta_list: List[Dict],
        overwrite: bool,
        errors: List[str],
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
                content = zf.read(zip_path).decode("utf-8", errors="replace")
            except KeyError:
                errors.append(f"קובץ גדול חסר ב-ZIP: {zip_path}")
                continue
            except Exception as e:
                errors.append(f"שגיאה בקריאת {zip_path}: {e}")
                continue

            # דלג אם התוכן זהה (מונע delete + insert מיותרים)
            if existing and overwrite:
                existing_content = existing.get("content", "")
                if existing_content == content:
                    continue

            try:
                large_file = LargeFile(
                    user_id=user_id,
                    file_name=file_name,
                    content=content,
                    programming_language=meta.get("programming_language", "text"),
                    file_size=len(content.encode("utf-8")),
                    lines_count=len(content.split("\n")),
                    description=meta.get("description", ""),
                    tags=list(meta.get("tags") or []),
                )
                self.db.save_large_file(large_file)
                count += 1
            except Exception as e:
                errors.append(f"שגיאה בשמירת קובץ גדול {file_name}: {e}")

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
            errors.append(f"שגיאה באתחול CollectionsManager: {e}")
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
                errors.append(f"שגיאה ביצירת אוסף '{coll.get('name', '')}': {e}")

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
                errors.append(f"שגיאה בהוספת פריטים לאוסף: {e}")

        return collections_count, items_count

    def _restore_bookmarks(
        self, user_id: int, bookmarks: List[Dict], errors: List[str]
    ) -> int:
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

                    # בדיקת כפילות — לא נוסיף אם כבר קיימת סימניה באותו מיקום
                    existing = raw_db.file_bookmarks.find_one({
                        "user_id": user_id,
                        "file_id": file_id,
                        "line_number": line_number,
                    })
                    if existing:
                        continue

                    # insert ישיר (לא toggle!) כדי לא למחוק סימניות קיימות
                    doc = {
                        "user_id": user_id,
                        "file_id": file_id,
                        "file_name": file_name,
                        "file_path": bm.get("file_path", file_name),
                        "line_number": line_number,
                        "line_text": bm.get("line_text", ""),
                        "note": bm.get("note", ""),
                        "color": bm.get("color", "yellow"),
                        "anchor_id": bm.get("anchor_id"),
                        "anchor_text": bm.get("anchor_text"),
                        "anchor_type": bm.get("anchor_type"),
                        "created_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
                    }
                    raw_db.file_bookmarks.insert_one(doc)
                    count += 1
                except Exception:
                    continue
        except Exception as e:
            errors.append(f"שגיאה בשחזור סימניות: {e}")

        return count

    def _restore_sticky_notes(
        self, user_id: int, notes: List[Dict], errors: List[str]
    ) -> int:
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

                    if file_name:
                        file_doc = self.db.get_file(user_id, file_name)
                        if file_doc and isinstance(file_doc, dict):
                            new_file_id = str(file_doc.get("_id", ""))

                    # אם אין file_name, ננסה להשתמש ב-scope_id ישן (best-effort)
                    if not new_file_id and not file_name:
                        continue  # לא ניתן לשייך את הפתקית

                    # חישוב scope_id חדש — חייב להתאים ל-_make_scope_id בדיוק:
                    # normalized = re.sub(r"\s+", " ", file_name.strip()).lower()
                    # digest = sha256(f"{user_id}::{normalized}").hexdigest()[:16]
                    # scope_id = f"user:{user_id}:file:{digest}"
                    import re
                    import hashlib
                    scope_id = None
                    if file_name:
                        normalized = re.sub(r"\s+", " ", str(file_name).strip()).lower()
                        digest = hashlib.sha256(
                            f"{user_id}::{normalized}".encode("utf-8")
                        ).hexdigest()[:16]
                        scope_id = f"user:{user_id}:file:{digest}"

                    content = note.get("content", "")

                    # בדיקת כפילות — דלג אם כבר קיימת פתקית עם אותו תוכן ומיקום
                    dup_query = {
                        "user_id": int(user_id),
                        "content": content,
                    }
                    if scope_id:
                        dup_query["scope_id"] = scope_id
                    elif new_file_id:
                        dup_query["file_id"] = new_file_id
                    existing_note = raw_db.sticky_notes.find_one(dup_query)
                    if existing_note:
                        continue

                    doc = {
                        "user_id": int(user_id),
                        "file_id": new_file_id or "",
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
            errors.append(f"שגיאה בשחזור פתקיות: {e}")

        return count

    def _restore_preferences(
        self, user_id: int, prefs: Dict[str, Any], errors: List[str]
    ) -> bool:
        """משחזר העדפות משתמש."""
        try:
            raw_db = getattr(self.db, "db", None)
            if raw_db is None:
                return False
            # הסר שדות שלא צריך לדרוס
            prefs.pop("_id", None)
            prefs.pop("user_id", None)
            raw_db.user_preferences.update_one(
                {"user_id": user_id},
                {"$set": prefs},
                upsert=True,
            )
            return True
        except Exception as e:
            errors.append(f"שגיאה בשחזור העדפות: {e}")
            return False

    def _restore_drive_prefs(
        self, user_id: int, prefs: Dict[str, Any], errors: List[str]
    ) -> bool:
        """משחזר העדפות Drive.

        משתמש ב-save_drive_prefs שעושה merge עם הקיים (לא דריסה מלאה).
        """
        try:
            if not prefs:
                return False
            return self.db.save_drive_prefs(user_id, prefs)
        except Exception as e:
            errors.append(f"שגיאה בשחזור העדפות Drive: {e}")
            return False

    # ================================================================
    #  עזרים
    # ================================================================
    @staticmethod
    def _read_json_from_zip(zf: zipfile.ZipFile, path: str, errors: List[str]) -> Any:
        """קורא וממיר קובץ JSON מתוך ה-ZIP."""
        try:
            raw = zf.read(path)
            return json.loads(raw)
        except KeyError:
            # קובץ לא קיים — לא שגיאה קריטית
            return None
        except Exception as e:
            errors.append(f"שגיאה בקריאת {path}: {e}")
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
```

### נקודות מפתח בשירות

- **ללא `code` בשאילתת רשימה:** `get_user_files` מחזיר ברירת מחדל ללא שדות כבדים (בהתאם ל-`HEAVY_FIELDS_EXCLUDE_PROJECTION`). קריאת תוכן מלא מתבצעת רק עם `get_file()` עבור כל קובץ בנפרד.
- **גודל ZIP מוגבל:** בשחזור, מגבלת 100MB למניעת העמסה.
- **`_safe_zip_path`:** מונע path traversal (למשל `../../etc/passwd`).
- **`overwrite` parameter:** מאפשר למשתמש לבחור האם לדרוס קבצים קיימים בשחזור.

---

## שלב 2: Blueprint — `webapp/backup_api.py`

Blueprint חדש עבור ה-API endpoints.

```python
"""
Personal Backup API — ייצוא ושחזור גיבוי אישי.

Endpoints:
- GET  /api/backup/export   — הורדת ZIP עם כל נתוני המשתמש
- POST /api/backup/restore  — שחזור נתונים מקובץ ZIP
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, jsonify, request, send_file, session

logger = logging.getLogger(__name__)

try:
    from observability import emit_event
except Exception:
    def emit_event(event: str, severity: str = "info", **fields):
        return None

try:
    from observability_instrumentation import traced
except Exception:
    def traced(*_a, **_k):
        def _inner(f):
            return f
        return _inner

backup_bp = Blueprint("backup", __name__)


def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"ok": False, "error": "נדרש להתחבר"}), 401
        return f(*args, **kwargs)
    return decorated


def _get_db():
    from webapp.app import get_db
    return get_db()


def _get_backup_service():
    from services.personal_backup_service import PersonalBackupService
    return PersonalBackupService(_get_db())


# גודל מקסימלי לקובץ ZIP (100MB)
MAX_UPLOAD_SIZE = 100 * 1024 * 1024


@backup_bp.route("/api/backup/export", methods=["GET"])
@_require_auth
@traced("backup.export")
def export_backup():
    """ייצוא גיבוי אישי כ-ZIP."""
    user_id = session["user_id"]

    try:
        service = _get_backup_service()
        buffer = service.export_user_data(int(user_id))

        # שם קובץ עם תאריך
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"codebot_backup_{user_id}_{ts}.zip"

        response = send_file(
            buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=filename,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    except Exception as e:
        logger.error(f"שגיאה בייצוא גיבוי: {e}")
        emit_event("personal_backup_export_error", severity="error",
                    user_id=int(user_id), error=str(e))
        return jsonify({"ok": False, "error": "שגיאה ביצירת הגיבוי"}), 500


@backup_bp.route("/api/backup/restore", methods=["POST"])
@_require_auth
@traced("backup.restore")
def restore_backup():
    """שחזור מגיבוי ZIP."""
    user_id = session["user_id"]

    # בדיקת קובץ
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "לא נבחר קובץ"}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"ok": False, "error": "לא נבחר קובץ"}), 400

    if not uploaded.filename.lower().endswith(".zip"):
        return jsonify({"ok": False, "error": "יש להעלות קובץ ZIP בלבד"}), 400

    # קריאת התוכן
    zip_bytes = uploaded.read()
    if len(zip_bytes) > MAX_UPLOAD_SIZE:
        return jsonify({
            "ok": False,
            "error": f"הקובץ גדול מדי (מקסימום {MAX_UPLOAD_SIZE // (1024*1024)}MB)",
        }), 413

    # פרמטרים
    overwrite = request.form.get("overwrite", "false").lower() in ("true", "1", "yes")

    try:
        service = _get_backup_service()
        result = service.restore_user_data(int(user_id), zip_bytes, overwrite=overwrite)
        return jsonify(result)

    except Exception as e:
        logger.error(f"שגיאה בשחזור גיבוי: {e}")
        emit_event("personal_backup_restore_error", severity="error",
                    user_id=int(user_id), error=str(e))
        return jsonify({"ok": False, "error": "שגיאה בשחזור הגיבוי"}), 500
```

---

## שלב 3: רישום ה-Blueprint — `webapp/app.py`

צריך להוסיף שורה אחת לרישום ה-Blueprint בקובץ `webapp/app.py`, ליד שאר הרישומים:

```python
# בתוך הפונקציה שמגדירה את ה-app (בדרך כלל create_app או app setup):
from webapp.backup_api import backup_bp
app.register_blueprint(backup_bp)
```

### איפה בדיוק?

חפשו את הבלוק שרושם blueprints אחרים, למשל:
```python
app.register_blueprint(collections_bp, url_prefix='/api/collections')
app.register_blueprint(bookmarks_bp)
```

הוסיפו שם:
```python
from webapp.backup_api import backup_bp
app.register_blueprint(backup_bp)
```

> **שימו לב:** ה-URL prefix כבר מוגדר ב-route עצמו (`/api/backup/...`), אז אין צורך ב-`url_prefix` ברישום.

---

## שלב 4: ממשק משתמש — עדכון `webapp/templates/settings.html`

מוסיפים section חדש לדף ההגדרות, **אחרי** הסקשן של "הגדרות סשן":

```html
<div class="glass-card" id="backup-section">
  <h2 class="section-title">
    <i class="fas fa-download"></i>
    גיבוי אישי
  </h2>
  <p style="opacity: 0.7; margin-bottom: 1.5rem">
    הורד עותק מלא של כל הקבצים, האוספים, הסימניות וההגדרות שלך — או שחזר מגיבוי קודם.
  </p>

  <div style="display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-start">
    <!-- כפתור ייצוא -->
    <div style="flex: 1; min-width: 280px">
      <div class="glass-card" style="background: rgba(255,255,255,0.05)">
        <h3 style="margin: 0 0 0.75rem 0; font-size: 1.1rem">
          <i class="fas fa-file-archive"></i>
          הורד גיבוי
        </h3>
        <p style="opacity: 0.7; font-size: 0.9rem; margin-bottom: 1rem">
          קובץ ZIP עם כל הנתונים שלך. מומלץ להוריד מדי פעם לשמירה.
        </p>
        <button id="btn-export-backup" class="btn btn-primary" onclick="exportBackup()" style="width: 100%">
          <i class="fas fa-download"></i>
          הורד גיבוי מלא
        </button>
        <div id="export-status" style="margin-top: 0.75rem; display: none"></div>
      </div>
    </div>

    <!-- כפתור שחזור -->
    <div style="flex: 1; min-width: 280px">
      <div class="glass-card" style="background: rgba(255,255,255,0.05)">
        <h3 style="margin: 0 0 0.75rem 0; font-size: 1.1rem">
          <i class="fas fa-upload"></i>
          שחזור מגיבוי
        </h3>
        <p style="opacity: 0.7; font-size: 0.9rem; margin-bottom: 1rem">
          בחר קובץ ZIP שהורדת קודם כדי לשחזר את הנתונים.
        </p>
        <input type="file" id="restore-file-input" accept=".zip"
               style="display: none" onchange="handleRestoreFile(this)">
        <button id="btn-restore-backup" class="btn btn-secondary"
                onclick="document.getElementById('restore-file-input').click()"
                style="width: 100%">
          <i class="fas fa-upload"></i>
          שחזר מקובץ ZIP
        </button>

        <!-- אפשרות דריסה -->
        <label style="display: flex; align-items: center; gap: 0.5rem; margin-top: 0.75rem;
                       font-size: 0.85rem; opacity: 0.8; cursor: pointer">
          <input type="checkbox" id="restore-overwrite">
          עדכן קבצים קיימים (יווצר גרסה חדשה, ההיסטוריה נשמרת)
        </label>

        <div id="restore-status" style="margin-top: 0.75rem; display: none"></div>
      </div>
    </div>
  </div>
</div>
```

---

## שלב 5: JavaScript — הוספת סקריפט בתחתית `settings.html`

מוסיפים את הסקריפט הבא בתחתית הקובץ, לפני `{% endblock %}`:

```html
<script>
// XSS-safe: escape HTML entities לפני הזרקה ל-innerHTML
function _esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

async function exportBackup() {
  const btn = document.getElementById('btn-export-backup');
  const status = document.getElementById('export-status');
  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> מכין גיבוי...';
  status.style.display = 'none';

  try {
    const resp = await fetch('/api/backup/export');
    if (!resp.ok) {
      let msg = 'שגיאה ביצירת הגיבוי';
      try {
        const data = await resp.json();
        msg = data.error || msg;
      } catch (_) {}
      throw new Error(msg);
    }

    // הורדת הקובץ
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    // לקחת את שם הקובץ מה-header אם יש
    const disposition = resp.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="?([^";\n]+)"?/);
    a.download = match ? match[1] : 'codebot_backup.zip';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    status.style.display = 'block';
    status.innerHTML = '<span style="color: #4ade80"><i class="fas fa-check-circle"></i> הגיבוי הורד בהצלחה</span>';
  } catch (err) {
    status.style.display = 'block';
    status.innerHTML = '<span style="color: #f87171"><i class="fas fa-exclamation-circle"></i> ' + _esc(err.message) + '</span>';
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-download"></i> הורד גיבוי מלא';
  }
}

async function handleRestoreFile(input) {
  const file = input.files[0];
  if (!file) return;

  const status = document.getElementById('restore-status');
  const btn = document.getElementById('btn-restore-backup');
  const overwrite = document.getElementById('restore-overwrite').checked;

  // אישור מהמשתמש
  const msg = overwrite
    ? 'שחזור עם עדכון קבצים קיימים (תיווצר גרסה חדשה). להמשיך?'
    : 'שחזור מגיבוי — קבצים קיימים לא ישתנו. להמשיך?';
  if (!confirm(msg)) {
    input.value = '';
    return;
  }

  btn.disabled = true;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> משחזר...';
  status.style.display = 'none';

  try {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('overwrite', overwrite ? 'true' : 'false');

    const resp = await fetch('/api/backup/restore', {
      method: 'POST',
      body: formData,
    });

    const data = await resp.json();

    if (!data.ok) {
      throw new Error(data.error || 'שגיאה בשחזור');
    }

    const r = data.restored || {};
    let summary = '<b>שחזור הושלם:</b><br>';
    if (r.files > 0) summary += `קבצים: ${r.files}<br>`;
    if (r.large_files > 0) summary += `קבצים גדולים: ${r.large_files}<br>`;
    if (r.collections > 0) summary += `אוספים: ${r.collections}<br>`;
    if (r.collection_items > 0) summary += `פריטים באוספים: ${r.collection_items}<br>`;
    if (r.bookmarks > 0) summary += `סימניות: ${r.bookmarks}<br>`;
    if (r.sticky_notes > 0) summary += `פתקיות: ${r.sticky_notes}<br>`;
    if (r.preferences) summary += `העדפות: שוחזרו<br>`;
    if (r.drive_prefs) summary += `העדפות Drive: שוחזרו<br>`;

    if (data.errors && data.errors.length > 0) {
      summary += `<br><span style="color: #fbbf24">${data.errors.length} שגיאות (ראה console)</span>`;
      console.warn('Restore errors:', data.errors);
    }

    status.style.display = 'block';
    status.innerHTML = '<div style="color: #4ade80">' + summary + '</div>';
  } catch (err) {
    status.style.display = 'block';
    status.innerHTML = '<span style="color: #f87171"><i class="fas fa-exclamation-circle"></i> ' + _esc(err.message) + '</span>';
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-upload"></i> שחזר מקובץ ZIP';
    input.value = '';
  }
}
</script>
```

---

## שלב 6: טסטים — `tests/test_personal_backup.py`

```python
"""
טסטים ליחידת הגיבוי האישי.

חשוב: כל הפעולות על תיקיות זמניות (tmp_path) בלבד.
"""
import json
import zipfile
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_db():
    """יוצר DatabaseManager מדומה עם נתוני דוגמה."""
    db = MagicMock()

    # קבצים רגילים
    db.get_user_files.return_value = [
        {
            "file_name": "hello.py",
            "programming_language": "python",
            "description": "Hello world",
            "tags": ["python", "demo"],
            "is_favorite": True,
            "is_pinned": False,
            "pin_order": 0,
            "version": 1,
            "created_at": None,
            "updated_at": None,
        }
    ]
    db.get_file.return_value = {
        "_id": "abc123",
        "code": "print('hello')",
        "file_name": "hello.py",
    }

    # קבצים גדולים
    db.get_user_large_files.return_value = ([], 0)

    # Drive prefs
    db.get_drive_prefs.return_value = {}

    # Large file
    db.get_large_file.return_value = None

    # DB object (for direct collection access)
    mock_raw_db = MagicMock()
    mock_raw_db.sticky_notes.find.return_value = []
    mock_raw_db.user_preferences.find_one.return_value = {}
    db.db = mock_raw_db

    return db


@pytest.fixture
def backup_service(mock_db):
    from services.personal_backup_service import PersonalBackupService
    return PersonalBackupService(mock_db)


class TestExport:
    def test_export_creates_valid_zip(self, backup_service):
        """בדיקה שה-export מייצר ZIP תקין עם backup_info.json."""
        buffer = backup_service.export_user_data(user_id=12345)
        assert buffer is not None

        with zipfile.ZipFile(buffer, "r") as zf:
            names = zf.namelist()
            assert "backup_info.json" in names
            assert "metadata/files.json" in names

            info = json.loads(zf.read("backup_info.json"))
            assert info["user_id"] == 12345
            assert info["version"] == 1
            assert info["files_count"] == 1

    def test_export_includes_file_content(self, backup_service):
        """בדיקה שתוכן הקבצים נכלל ב-ZIP."""
        buffer = backup_service.export_user_data(user_id=12345)

        with zipfile.ZipFile(buffer, "r") as zf:
            content = zf.read("files/hello.py").decode("utf-8")
            assert content == "print('hello')"

    def test_export_includes_metadata(self, backup_service):
        """בדיקה שמטאדאטה נכללת ב-ZIP."""
        buffer = backup_service.export_user_data(user_id=12345)

        with zipfile.ZipFile(buffer, "r") as zf:
            meta = json.loads(zf.read("metadata/files.json"))
            regular = meta["regular_files"]
            assert len(regular) == 1
            assert regular[0]["file_name"] == "hello.py"
            assert regular[0]["is_favorite"] is True


class TestRestore:
    def _make_zip(self, files_dict: dict) -> bytes:
        """יוצר ZIP מדומה עם קבצים נתונים."""
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for path, content in files_dict.items():
                if isinstance(content, dict) or isinstance(content, list):
                    zf.writestr(path, json.dumps(content))
                else:
                    zf.writestr(path, str(content))
        return buf.getvalue()

    def test_restore_basic(self, backup_service, mock_db):
        """בדיקת שחזור בסיסי."""
        mock_db.get_file.return_value = None  # אין קובץ קיים
        mock_db.save_code_snippet.return_value = True

        zip_bytes = self._make_zip({
            "backup_info.json": {"version": 1},
            "metadata/files.json": {
                "regular_files": [{
                    "file_name": "test.py",
                    "programming_language": "python",
                    "description": "",
                    "tags": [],
                }],
                "large_files": [],
            },
            "files/test.py": "# test file",
        })

        result = backup_service.restore_user_data(12345, zip_bytes)
        assert result["ok"] is True
        assert result["restored"]["files"] == 1
        mock_db.save_code_snippet.assert_called_once()

    def test_restore_rejects_bad_zip(self, backup_service):
        """בדיקה ש-ZIP לא תקין נדחה."""
        result = backup_service.restore_user_data(12345, b"not a zip")
        assert result["ok"] is False
        assert "ZIP" in result["error"]

    def test_restore_rejects_oversized(self, backup_service):
        """בדיקה שקובץ גדול מדי נדחה."""
        from services.personal_backup_service import MAX_RESTORE_ZIP_SIZE
        fake_big = b"x" * (MAX_RESTORE_ZIP_SIZE + 1)
        result = backup_service.restore_user_data(12345, fake_big)
        assert result["ok"] is False
        assert "גדול" in result["error"]

    def test_restore_skip_existing_no_overwrite(self, backup_service, mock_db):
        """בדיקה שקבצים קיימים לא נדרסים כש-overwrite=False."""
        mock_db.get_file.return_value = {"file_name": "test.py", "code": "old"}

        zip_bytes = self._make_zip({
            "backup_info.json": {"version": 1},
            "metadata/files.json": {
                "regular_files": [{"file_name": "test.py", "programming_language": "python"}],
                "large_files": [],
            },
            "files/test.py": "new content",
        })

        result = backup_service.restore_user_data(12345, zip_bytes, overwrite=False)
        assert result["ok"] is True
        assert result["restored"]["files"] == 0  # לא נשמר כי כבר קיים
```

---

## צ'קליסט לפני merge

- [ ] עיינתי ב-[CodeBot Docs](https://amirbiron.github.io/CodeBot/) לפני שינוי טסטים
- [ ] קבצים חדשים:
  - `services/personal_backup_service.py`
  - `webapp/backup_api.py`
  - `tests/test_personal_backup.py`
- [ ] קבצים מעודכנים:
  - `webapp/app.py` (רישום blueprint)
  - `webapp/templates/settings.html` (UI section + JS)
- [ ] אין שימוש ב-`rm -rf` או מחיקות קבצים מחוץ ל-tmp
- [ ] כל הגישות ל-DB עוברות דרך `DatabaseManager` או managers מוכרים
- [ ] ייצוא משתמש ב-`BytesIO` + `send_file` (כמו ב-`collections_api.py`)
- [ ] שחזור מאמת גודל ZIP + פורמט לפני עיבוד
- [ ] `_safe_zip_path` מונע path traversal
- [ ] אין חשיפת סודות/PII בלוגים
- [ ] טסטים עובדים עם mock בלבד (ללא DB אמיתי)
- [ ] `./gradlew test detekt ktlintCheck` (לא רלוונטי לפייתון — הריצו `pytest`)

---

## שיקולי rollback

- **הפיצ'ר עצמאי לחלוטין** — אם יש בעיה, מספיק להסיר את ה-blueprint registration מ-`app.py` והסקשן מ-`settings.html`.
- **לא משנה schema של DB** — לא צריך מיגרציה.
- **אין side effects** — ייצוא הוא read-only, שחזור יוצר מסמכים חדשים בלבד (לא מוחק).

---

## שיפורים עתידיים (לא בסקופ הנוכחי)

1. **גיבוי מתוזמן** — חיבור ל-scheduler קיים לגיבוי אוטומטי ל-Google Drive
2. **גיבוי סלקטיבי** — בחירת רכיבים ספציפיים (רק קבצים, רק אוספים, וכו')
3. **Progress bar** — streaming עם Server-Sent Events למשתמשים עם הרבה קבצים
4. **הצפנה** — הגנה על ה-ZIP בסיסמה
5. **מגבלת תדירות** — rate limit ליצירת גיבויים (למשל פעם בשעה)
6. **היסטוריית גיבויים** — שמירת metadata של גיבויים קודמים ב-DB
