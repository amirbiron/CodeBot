from typing import Any, BinaryIO, Dict, List, Optional, Tuple, Set
import os
import tempfile
import zipfile
import json
from datetime import datetime, timezone
from pathlib import Path
import logging
from contextlib import suppress

try:
    import gridfs  # from pymongo
except Exception:  # pragma: no cover
    gridfs = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

class BackupInfo:
    """מידע על גיבוי"""
    def __init__(self, backup_id: str, user_id: int, created_at: datetime, file_count: int, total_size: int, backup_type: str, status: str, file_path: str, repo: Optional[str], path: Optional[str], metadata: Optional[Dict[str, Any]]):
        self.backup_id = backup_id
        self.user_id = user_id
        self.created_at = created_at
        self.file_count = file_count
        self.total_size = total_size
        self.backup_type = backup_type
        self.status = status
        self.file_path = file_path
        self.repo = repo
        self.path = path
        self.metadata = metadata

class BackupManager:
    """מנהל גיבויים"""
    
    def __init__(self):
        # מצב אחסון: mongo (GridFS) או fs (קבצים)
        self.storage_mode = os.getenv("BACKUPS_STORAGE", "mongo").strip().lower()

        # העדף תיקייה מתמשכת עבור גיבויים (נשמרת בין דיפלויים אם קיימת)
        # נסה לפי סדר: BACKUPS_DIR מהסביבה → /app/backups → /data/backups → /var/lib/code_keeper/backups
        persistent_candidates = [
            os.getenv("BACKUPS_DIR"),
            "/app/backups",
            "/data/backups",
            "/var/lib/code_keeper/backups",
        ]
        chosen_dir: Optional[Path] = None
        for cand in persistent_candidates:
            if not cand:
                continue
            try:
                p = Path(cand)
                p.mkdir(parents=True, exist_ok=True)
                # וידוא שניתן לכתוב
                test_file = p / ".write_test"
                try:
                    with open(test_file, "w") as tf:
                        tf.write("ok")
                    test_file.unlink(missing_ok=True)  # type: ignore[arg-type]
                except Exception:
                    # אם אי אפשר לכתוב – נסה מועמד הבא
                    continue
                chosen_dir = p
                break
            except Exception:
                continue

        if chosen_dir is None:
            # נפילה לתיקיית temp אם אין נתיב מתמשך זמין
            chosen_dir = Path(tempfile.gettempdir()) / "code_keeper_backups"
            chosen_dir.mkdir(exist_ok=True)

        self.backup_dir = chosen_dir

        # תיקיית legacy: תמיכה בקריאה גם מהמיקום הישן (אם השתמש בעבר ב-temp)
        # נשמור גם על תמיכה ב-"/app/backups" כנתיב חיפוש נוסף אם לא נבחר כבר
        legacy_candidates: List[Path] = []
        try:
            legacy_candidates.append(Path(tempfile.gettempdir()) / "code_keeper_backups")
        except Exception:
            pass
        try:
            app_backups = Path("/app/backups")
            if app_backups != self.backup_dir:
                legacy_candidates.append(app_backups)
        except Exception:
            pass
        # שמור נתיב legacy ראשי למטרות תאימות (ישומש בחיפוש)
        self.legacy_backup_dir = legacy_candidates[0] if legacy_candidates else None
        self.max_backup_size = 100 * 1024 * 1024  # 100MB

    # =============================
    # GridFS helpers (Mongo storage)
    # =============================
    def _get_gridfs(self):
        if self.storage_mode != "mongo":
            return None
        if gridfs is None:
            return None
        try:
            # שימוש במסד הנתונים הגלובלי הקיים
            from database import db as global_db
            mongo_db = getattr(global_db, "db", None)
            if not mongo_db:
                return None
            # אוסף ייעודי "backups"
            return gridfs.GridFS(mongo_db, collection="backups")
        except Exception:
            return None

    def save_backup_bytes(self, data: bytes, metadata: Dict[str, Any]) -> Optional[str]:
        """שומר ZIP של גיבוי בהתאם למצב האחסון ומחזיר backup_id או None במקרה כשל.

        אם storage==mongo: שומר ל-GridFS עם המטאדטה.
        אם storage==fs: שומר לקובץ תחת backup_dir.
        """
        try:
            backup_id = metadata.get("backup_id") or f"backup_{int(datetime.now(timezone.utc).timestamp())}"
            # הבטח זיהוי בקובץ
            filename = f"{backup_id}.zip"

            if self.storage_mode == "mongo":
                fs = self._get_gridfs()
                if fs is None:
                    # נפילה לאחסון קבצים
                    target_path = self.backup_dir / filename
                    with open(target_path, "wb") as f:
                        f.write(data)
                    return backup_id
                # שמור ל-GridFS
                # אם כבר קיים אותו backup_id – מחק ישן
                with suppress(Exception):
                    for fdoc in fs.find({"filename": filename}):
                        fs.delete(fdoc._id)
                fs.put(data, filename=filename, metadata=metadata)
                return backup_id

            # ברירת מחדל: קבצים
            target_path = self.backup_dir / filename
            with open(target_path, "wb") as f:
                f.write(data)
            return backup_id
        except Exception as e:
            logger.warning(f"save_backup_bytes failed: {e}")
            return None

    def save_backup_file(self, file_path: str) -> Optional[str]:
        """שומר קובץ ZIP קיים לאחסון היעד (Mongo/FS) ומחזיר backup_id אם הצליח."""
        try:
            # נסה לקרוא metadata.json מתוך ה-ZIP
            metadata: Dict[str, Any] = {}
            try:
                with zipfile.ZipFile(file_path, 'r') as zf:
                    with suppress(Exception):
                        md_raw = zf.read('metadata.json')
                        metadata = json.loads(md_raw) if md_raw else {}
            except Exception:
                metadata = {}
            if "backup_id" not in metadata:
                # הפק מזהה מגיבוי
                metadata["backup_id"] = os.path.splitext(os.path.basename(file_path))[0]
            with open(file_path, 'rb') as f:
                data = f.read()
            return self.save_backup_bytes(data, metadata)
        except Exception as e:
            logger.warning(f"save_backup_file failed: {e}")
            return None

    def list_backups(self, user_id: int) -> List[BackupInfo]:
        """רשימת כל קבצי ה‑ZIP השמורים בבוט (לא רק כאלה בשם backup_*), ללא סינון לפי user_id.

        הערות:
        - אם קיים metadata.json, נשלוף ממנו נתונים (כולל user_id מקורי אם קיים) אך לא נסנן לפיו
        - אם אין מטאדטה, נטפל בהם כ‑generic_zip עם נפילה לאחור
        """

        backups: List[BackupInfo] = []

        try:
            # עבור על כל קובצי ה‑ZIP בכל התיקיות הרלוונטיות (ראשית + legacy/migration)
            search_dirs: List[Path] = [self.backup_dir]
            # הוסף נתיבי legacy נוספים אם זמינים
            extra_legacy: List[Path] = []
            try:
                if getattr(self, "legacy_backup_dir", None):
                    if isinstance(self.legacy_backup_dir, Path) and self.legacy_backup_dir.exists():
                        extra_legacy.append(self.legacy_backup_dir)
            except Exception:
                pass
            # ודא ש-/app/backups ייסרק גם אם הוא אינו ה-backup_dir
            try:
                app_backups = Path("/app/backups")
                if app_backups.exists() and app_backups != self.backup_dir:
                    extra_legacy.append(app_backups)
            except Exception:
                pass
            for d in extra_legacy:
                if d not in search_dirs:
                    search_dirs.append(d)

            seen_paths: Set[str] = set()

            # קבצים בדיסק
            for _dir in search_dirs:
                for backup_file in _dir.glob("*.zip"):
                    try:
                        resolved_path = str(backup_file.resolve())
                    except Exception:
                        resolved_path = str(backup_file)
                    if resolved_path in seen_paths:
                        continue
                    seen_paths.add(resolved_path)
                    try:
                        # ערכי ברירת מחדל
                        metadata: Optional[Dict[str, Any]] = None
                        backup_id: str = os.path.splitext(os.path.basename(backup_file))[0]
                        created_at: Optional[datetime] = None
                        file_count: int = 0
                        backup_type: str = "unknown"
                        repo: Optional[str] = None
                        path: Optional[str] = None

                        with zipfile.ZipFile(backup_file, 'r') as zf:
                            # נסה לקרוא metadata.json, אם קיים
                            try:
                                metadata_content = zf.read("metadata.json")
                                metadata = json.loads(metadata_content)
                            except Exception:
                                metadata = None

                            # הצגת כל קובצי ה‑ZIP שנשמרו בבוט, ללא תלות ב‑user_id
                            # שמירת ה‑user_id המקורי (אם קיים) תיעשה בשדה המידע החוזר
                            include: bool = True

                            # שלוף נתונים מהמטאדטה אם קיימת
                            if metadata is not None:
                                backup_id = metadata.get("backup_id") or backup_id
                                created_at_str = metadata.get("created_at")
                                if created_at_str:
                                    try:
                                        created_at = datetime.fromisoformat(created_at_str)
                                        # נרמל ל-aware TZ אם חסר
                                        if created_at.tzinfo is None:
                                            created_at = created_at.replace(tzinfo=timezone.utc)
                                    except Exception:
                                        created_at = None
                                fc_meta = metadata.get("file_count")
                                if isinstance(fc_meta, int):
                                    file_count = fc_meta
                                backup_type = metadata.get("backup_type", "unknown")
                                repo = metadata.get("repo")
                                path = metadata.get("path")
                            else:
                                # ZIP כללי ללא מטאדטה
                                backup_type = "generic_zip"

                            # אם אין created_at – נפל ל‑mtime של הקובץ
                            if not created_at:
                                try:
                                    created_at = datetime.fromtimestamp(os.path.getmtime(resolved_path), tz=timezone.utc)
                                except Exception:
                                    created_at = datetime.now(timezone.utc)

                            # אם אין file_count – מנה את הקבצים שאינם תיקיות
                            if file_count == 0:
                                try:
                                    with zipfile.ZipFile(resolved_path, 'r') as _zf_count:
                                        non_dirs = [n for n in _zf_count.namelist() if not n.endswith('/')]
                                        file_count = len(non_dirs)
                                except Exception:
                                    file_count = 0

                        backup_info = BackupInfo(
                            backup_id=backup_id,
                            user_id=(metadata.get("user_id") if metadata and metadata.get("user_id") is not None else user_id),
                            created_at=created_at,
                            file_count=file_count,
                            total_size=os.path.getsize(resolved_path),
                            backup_type=backup_type,
                            status="completed",
                            file_path=resolved_path,
                            repo=repo,
                            path=path,
                            metadata=metadata,
                        )

                        backups.append(backup_info)

                    except Exception as e:
                        logger.warning(f"שגיאה בקריאת גיבוי {backup_file}: {e}")
                        continue

            # קבצים ב-GridFS (Mongo) – נטען גם אותם
            try:
                fs = self._get_gridfs()
                if fs is not None:
                    # חפש את כל הקבצים; נסנן ואח"כ נציג לפי created_at
                    for fdoc in fs.find():
                        try:
                            md = getattr(fdoc, 'metadata', None) or {}
                            backup_id = md.get("backup_id") or os.path.splitext(fdoc.filename or "")[0] or str(getattr(fdoc, "_id", ""))
                            if not backup_id:
                                continue
                            if any(b.backup_id == backup_id for b in backups):
                                # כבר קיים מתוך הדיסק
                                continue
                            created_at = None
                            created_at_str = md.get("created_at")
                            if created_at_str:
                                with suppress(Exception):
                                    created_at = datetime.fromisoformat(created_at_str)
                                    if created_at and created_at.tzinfo is None:
                                        created_at = created_at.replace(tzinfo=timezone.utc)
                            if not created_at:
                                with suppress(Exception):
                                    created_at = getattr(fdoc, 'uploadDate', None)
                            file_count = int(md.get("file_count") or 0)
                            backup_type = md.get("backup_type", "unknown")
                            repo = md.get("repo")
                            path = md.get("path")
                            total_size = int(getattr(fdoc, 'length', 0) or 0)

                            # ודא עותק מקומי זמני כדי שתלויה בקוד קיים שעובד עם נתיב קובץ
                            local_path = self.backup_dir / f"{backup_id}.zip"
                            if not local_path.exists() or (total_size and local_path.stat().st_size != total_size):
                                try:
                                    grid_out = fs.get(fdoc._id)
                                    with open(local_path, 'wb') as lf:
                                        lf.write(grid_out.read())
                                except Exception:
                                    # אם נכשל יצירת עותק – דלג והמשך (לא נציג פריט לא שמיש)
                                    continue

                            backup_info = BackupInfo(
                                backup_id=backup_id,
                                user_id=(md.get("user_id") if md.get("user_id") is not None else user_id),
                                created_at=created_at or datetime.now(timezone.utc),
                                file_count=file_count,
                                total_size=total_size or (local_path.stat().st_size if local_path.exists() else 0),
                                backup_type=backup_type,
                                status="completed",
                                file_path=str(local_path),
                                repo=repo,
                                path=path,
                                metadata=md,
                            )
                            backups.append(backup_info)
                        except Exception:
                            continue
            except Exception:
                pass

            # מיון לפי תאריך יצירה
            backups.sort(key=lambda x: x.created_at, reverse=True)

        except Exception as e:
            logger.error(f"שגיאה ברשימת גיבויים: {e}")

        return backups

    def restore_from_backup(self, user_id: int, backup_path: str, overwrite: bool = True, purge: bool = False, extra_tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """משחזר קבצים מ-ZIP למסד הנתונים.

        - purge=True: מסמן את כל הקבצים הקיימים של המשתמש כלא פעילים לפני השחזור
        - overwrite=True: שמירה תמיד כגרסה חדשה עבור אותו שם (כברירת מחדל)
        החזרה: dict עם restored_files ו-errors
        """
        results: Dict[str, Any] = {"restored_files": 0, "errors": []}
        try:
            import zipfile
            from database import db
            from utils import detect_language_from_filename
            # פרה-תנאי
            if not os.path.exists(backup_path):
                results["errors"].append(f"backup file not found: {backup_path}")
                return results

            if purge:
                try:
                    existing = db.get_user_files(user_id, limit=10000) or []
                    for doc in existing:
                        try:
                            fname = doc.get('file_name')
                            if fname:
                                db.delete_file(user_id, fname)
                        except Exception as e:
                            results["errors"].append(f"purge failed for {doc.get('file_name')}: {e}")
                except Exception as e:
                    results["errors"].append(f"purge listing failed: {e}")

            with zipfile.ZipFile(backup_path, 'r') as zf:
                names = [n for n in zf.namelist() if not n.endswith('/') and n != 'metadata.json']
                for name in names:
                    try:
                        raw = zf.read(name)
                        text: str
                        try:
                            text = raw.decode('utf-8')
                        except Exception:
                            try:
                                text = raw.decode('latin-1')
                            except Exception as e:
                                results["errors"].append(f"decode failed for {name}: {e}")
                                continue
                        lang = detect_language_from_filename(name)
                        ok = db.save_file(user_id=user_id, file_name=name, code=text, programming_language=lang)
                        if ok:
                            results["restored_files"] += 1
                        else:
                            results["errors"].append(f"save failed for {name}")
                    except Exception as e:
                        results["errors"].append(f"restore failed for {name}: {e}")
        except Exception as e:
            results["errors"].append(str(e))
        return results

    def delete_backup(self, backup_id: str, user_id: int) -> bool:
        """מחיקת גיבוי"""
        
        try:
            # חפש את הגיבוי בשתי התיקיות (ברירת מחדל + legacy)
            candidate_files: List[Path] = []
            try:
                candidate_files.extend(list(self.backup_dir.glob(f"{backup_id}.zip")))
            except Exception:
                pass
            try:
                if getattr(self, 'legacy_backup_dir', None) and self.legacy_backup_dir.exists():
                    candidate_files.extend(list(self.legacy_backup_dir.glob(f"{backup_id}.zip")))
                
            except Exception:
                pass
            
            for backup_file in candidate_files:
                # וידוא שהגיבוי שייך למשתמש אם קיימת מטאדטה
                try:
                    with zipfile.ZipFile(backup_file, 'r') as zip_file:
                        try:
                            metadata_content = zip_file.read("metadata.json")
                            metadata = json.loads(metadata_content)
                            if metadata.get("user_id") == user_id:
                                backup_file.unlink()
                                logger.info(f"נמחק גיבוי: {backup_id}")
                                return True
                        except Exception:
                            # אין מטאדטה – דלג
                            continue
                except Exception:
                    continue
            
            logger.warning(f"גיבוי לא נמצא או לא שייך למשתמש: {backup_id}")
            return False
        
        except Exception as e:
            logger.error(f"שגיאה במחיקת גיבוי: {e}")
            return False

backup_manager = BackupManager()