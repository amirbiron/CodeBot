from typing import Any, BinaryIO, Dict, List, Optional, Tuple, Set
import os
import tempfile
import zipfile
import json
from datetime import datetime, timezone
from pathlib import Path
import logging
from contextlib import suppress
import io
import re
import shutil
import time

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
        # מנגנון התרעה פשוט למניעת הצפה
        self._last_disk_warn_ts: float = 0.0

    def _maybe_alert_low_space(self) -> None:
        """בדיקת מקום פנוי בדיסק לפני כתיבה והתרעה לאדמין אם נמוך.

        - סף ברירת מחדל: 200MB (ניתן לשינוי ב‑BACKUPS_DISK_MIN_FREE_BYTES)
        - Rate limit: התרעה אחת לכל 10 דקות כדי להימנע מספאם
        """
        try:
            # חישוב מקום פנוי על הפיילסיסטם של תיקיית הגיבויים
            usage = shutil.disk_usage(self.backup_dir)
            free_bytes = int(getattr(usage, 'free', 0) or 0)
            try:
                # תמיכה נכונה במשתנה סביבה ריק: אם ה‑ENV קיים אך ריק → השתמש בברירת המחדל
                _env_val = os.getenv("BACKUPS_DISK_MIN_FREE_BYTES")
                if _env_val is None or not str(_env_val).strip():
                    threshold = 200 * 1024 * 1024
                else:
                    threshold = int(_env_val)
            except Exception:
                threshold = 200 * 1024 * 1024
            limit = max(1, threshold)
            if free_bytes <= 0 or free_bytes < limit:
                now = time.time()
                if now - self._last_disk_warn_ts < 600:  # 10 דקות
                    return
                self._last_disk_warn_ts = now
                # נסה לפלוט אירוע מובנה + התראה פנימית
                try:
                    from observability import emit_event  # type: ignore
                except Exception:
                    emit_event = None  # type: ignore
                try:
                    from internal_alerts import emit_internal_alert  # type: ignore
                except Exception:
                    emit_internal_alert = None  # type: ignore
                msg = "⚠️ הדיסק כמעט מלא – מומלץ לנקות גיבויים או להגדיל נפח"
                details = {
                    "path": str(self.backup_dir),
                    "free_bytes": int(free_bytes),
                    "threshold_bytes": int(threshold),
                }
                try:
                    if emit_event is not None:
                        emit_event("disk_low_space", severity="warn", **details)
                except Exception:
                    pass
                try:
                    if emit_internal_alert is not None:
                        # סיכום קצר + פרטים טכניים לצפייה ב‑ChatOps/Telegram
                        emit_internal_alert("disk_low_space", severity="warn", summary=msg, **details)
                except Exception:
                    pass

                # הודעה ישירה למנהלים דרך הבוט (ADMIN_USER_IDS + BOT_TOKEN)
                try:
                    admins_raw = os.getenv("ADMIN_USER_IDS", "")
                    if admins_raw:
                        admin_ids = [int(x.strip()) for x in admins_raw.split(',') if x.strip().isdigit()]
                    else:
                        admin_ids = []
                except Exception:
                    admin_ids = []
                bot_token = os.getenv("BOT_TOKEN", "")
                if bot_token and admin_ids:
                    text = f"{msg}\nנתיב: {details['path']}\nפנוי: {details['free_bytes']:,}B (סף {details['threshold_bytes']:,}B)"
                    try:
                        # העדף http_sync.request אם זמין, אחרת requests
                        try:
                            from http_sync import request as _request  # type: ignore
                        except Exception:
                            _request = None  # type: ignore
                        api = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                        for admin_id in admin_ids:
                            payload = {"chat_id": int(admin_id), "text": text}
                            try:
                                if _request is not None:
                                    _request('POST', api, json=payload, timeout=5)
                                else:
                                    import requests  # type: ignore
                                    requests.post(api, json=payload, timeout=5)
                            except Exception:
                                continue
                    except Exception:
                        pass
        except Exception:
            # לא לשבור זרימה בגיבוי — התרעה היא best‑effort
            return

    def _is_safe_path(self, target: Path, allow_under: Path) -> bool:
        """בדיקת בטיחות למסלול לפני מחיקה/ניקוי.

        - מונע מחיקה של נתיבים מסוכנים ("/", HOME, או ה־PWD הנוכחי)
        - מאשר רק נתיבים שנמצאים תחת allow_under
        """
        try:
            rp_target = target.resolve()
            rp_base = allow_under.resolve()
            if str(rp_target) == "/" or str(rp_target) == str(Path.home()) or str(rp_target) == str(Path.cwd()):
                return False
            # דרוש שהנתיב יהיה מתחת ל־allow_under
            return str(rp_target).startswith(str(rp_base) + "/") or (str(rp_target) == str(rp_base))
        except Exception:
            return False

    def cleanup_expired_backups(
        self,
        retention_days: int | None = None,
        *,
        max_per_user: int | None = None,
        budget_seconds: float | None = None,
    ) -> dict:
        """ניקוי גיבויים ישנים ממערכת הקבצים ומ‑GridFS באופן מבוקר.

        פרמטרים:
        - retention_days: ימים לשמירת גיבוי לפני מחיקה (ברירת מחדל: BACKUPS_RETENTION_DAYS או 30)
        - max_per_user: כמות מקסימלית של גיבויים לשמירה לכל משתמש (ברירת מחדל: BACKUPS_MAX_PER_USER או None)
        - budget_seconds: תקציב זמן לניקוי כדי לא לחסום את ה־worker (ברירת מחדל: BACKUPS_CLEANUP_BUDGET_SECONDS או 3)

        החזרה: dict עם counters לסריקה/מחיקות ושגיאות.
        """
        from contextlib import suppress
        import time
        from datetime import datetime, timedelta, timezone
        import os

        # דגלי בטיחות: אפשר לכבות ניקוי רקע לחלוטין
        if str(os.getenv("DISABLE_BACKGROUND_CLEANUP", "")).lower() in ("1", "true", "yes", "on"):
            return {"skipped": True, "reason": "disabled_by_env"}

        # SAFE_MODE → אל תמחק מהדיסק (נחזיר skipped כדי להימנע מהפתעות בסביבת טסטים)
        if str(os.getenv("SAFE_MODE", "")).lower() in ("1", "true", "yes", "on"):
            return {"skipped": True, "reason": "safe_mode"}

        try:
            if retention_days is None:
                retention_days = int(os.getenv("BACKUPS_RETENTION_DAYS", "30") or 30)
        except Exception:
            retention_days = 30
        try:
            if max_per_user is None:
                val = os.getenv("BACKUPS_MAX_PER_USER", "")
                max_per_user = int(val) if val not in (None, "") else None
        except Exception:
            max_per_user = None
        try:
            if budget_seconds is None:
                budget_seconds = float(os.getenv("BACKUPS_CLEANUP_BUDGET_SECONDS", "3") or 3)
        except Exception:
            budget_seconds = 3.0

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=max(1, int(retention_days or 30)))
        deadline = time.time() + max(0.1, float(budget_seconds or 3.0))

        summary: dict = {
            "fs_scanned": 0,
            "fs_deleted": 0,
            "gridfs_scanned": 0,
            "gridfs_deleted": 0,
            "errors": [],
            "retention_days": int(retention_days or 30),
            "max_per_user": (int(max_per_user) if isinstance(max_per_user, int) else None),
        }

        # --- ניקוי במערכת הקבצים ---
        try:
            search_dirs: list[Path] = [self.backup_dir]
            # הוסף נתיבי legacy בטוחים בלבד
            with suppress(Exception):
                if getattr(self, "legacy_backup_dir", None) and isinstance(self.legacy_backup_dir, Path):
                    search_dirs.append(self.legacy_backup_dir)
            with suppress(Exception):
                app_backups = Path("/app/backups")
                if app_backups != self.backup_dir:
                    search_dirs.append(app_backups)

            # קיבוץ לפי משתמש
            by_user: dict[int | str, list[tuple[Path, datetime]]] = {}

            for base_dir in search_dirs:
                try:
                    for p in base_dir.glob("*.zip"):
                        if time.time() > deadline:
                            break
                        summary["fs_scanned"] += 1
                        # חילוץ owner ו‑created_at מתוך ה‑ZIP (best‑effort)
                        owner: int | str | None = None
                        created_at: datetime | None = None
                        with suppress(Exception):
                            with zipfile.ZipFile(p, 'r') as zf:
                                with suppress(Exception):
                                    md_raw = zf.read('metadata.json')
                                    md = json.loads(md_raw) if md_raw else {}
                                    uid_val = md.get("user_id")
                                    if isinstance(uid_val, int):
                                        owner = uid_val
                                    elif isinstance(uid_val, str) and uid_val.isdigit():
                                        owner = int(uid_val)
                                    cat = md.get("created_at")
                                    if isinstance(cat, str):
                                        try:
                                            created_at = datetime.fromisoformat(cat)
                                            if created_at.tzinfo is None:
                                                created_at = created_at.replace(tzinfo=timezone.utc)
                                        except Exception:
                                            created_at = None
                        # fallback
                        if created_at is None:
                            with suppress(Exception):
                                created_at = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                        if owner is None:
                            # נסה לחלץ מ‑backup_<user>_*
                            name = p.stem
                            with suppress(Exception):
                                import re
                                m = re.match(r"^backup_(\d+)_", name)
                                if m:
                                    owner = int(m.group(1))
                        key = owner if owner is not None else "unknown"
                        if created_at is None:
                            created_at = now
                        by_user.setdefault(key, []).append((p, created_at))
                except Exception as e:
                    summary["errors"].append(f"fs_scan:{base_dir}:{e}")

            # קבע מועמדים למחיקה לפי retention ו‑max_per_user
            candidates: list[Path] = []
            candidate_set: set[str] = set()

            def _add_candidate(p: Path) -> None:
                # הוספה O(1) עם סט למניעת כפילויות במקום 'p not in list'
                try:
                    rp = str(p.resolve())
                except Exception:
                    rp = str(p)
                if rp in candidate_set:
                    return
                candidate_set.add(rp)
                candidates.append(p)
            for key, items in by_user.items():
                # מיון מהחדש לישן
                items.sort(key=lambda t: t[1], reverse=True)
                # חריגה ממכסה
                if isinstance(max_per_user, int) and max_per_user > 0 and len(items) > max_per_user:
                    for p, _dt in items[max_per_user:]:
                        _add_candidate(p)
                # ישנים מעבר ל‑cutoff
                for p, dt in items:
                    if dt < cutoff:
                        _add_candidate(p)

            # מחיקה מבוקרת
            for p in candidates:
                if time.time() > deadline:
                    break
                # ודא שהקובץ באמת נמצא תחת אחד מהנתיבים המותרים
                allowed_ok = any(self._is_safe_path(p, base) for base in search_dirs if isinstance(base, Path))
                if not allowed_ok:
                    summary["errors"].append(f"unsafe_path:{p}")
                    continue
                try:
                    if p.exists():
                        p.unlink()
                        summary["fs_deleted"] += 1
                except Exception as e:
                    summary["errors"].append(f"fs_delete:{p}:{e}")
        except Exception as e:
            summary["errors"].append(f"fs_cleanup:{e}")

        # --- ניקוי ב‑GridFS (אם קיים) ---
        try:
            fs = self._get_gridfs()
        except Exception:
            fs = None
        if fs is not None and time.time() <= deadline:
            try:
                by_user_g: dict[int | str, list[tuple[object, datetime]]] = {}
                # איטרציה עצלה כדי לכבד תקציב זמן; הימנע מ-materialize מלא
                try:
                    cursor = fs.find()
                except Exception:
                    cursor = []
                for fdoc in cursor:
                    if time.time() > deadline:
                        break
                    summary["gridfs_scanned"] += 1
                    owner: int | str | None = None
                    created_at: datetime | None = None
                    md = getattr(fdoc, 'metadata', None) or {}
                    with suppress(Exception):
                        uid_val = md.get('user_id')
                        if isinstance(uid_val, int):
                            owner = uid_val
                        elif isinstance(uid_val, str) and uid_val.isdigit():
                            owner = int(uid_val)
                    with suppress(Exception):
                        created_at = getattr(fdoc, 'uploadDate', None)
                        if created_at and getattr(created_at, 'tzinfo', None) is None:
                            created_at = created_at.replace(tzinfo=timezone.utc)
                    if created_at is None:
                        with suppress(Exception):
                            cat = md.get('created_at')
                            if isinstance(cat, str):
                                created_at = datetime.fromisoformat(cat)
                                if created_at and created_at.tzinfo is None:
                                    created_at = created_at.replace(tzinfo=timezone.utc)
                    if created_at is None:
                        created_at = now
                    key = owner if owner is not None else "unknown"
                    by_user_g.setdefault(key, []).append((fdoc, created_at))

                # מועמדים למחיקה
                cand_ids: list[object] = []
                cand_id_set: set[object] = set()
                for key, items in by_user_g.items():
                    items.sort(key=lambda t: t[1], reverse=True)
                    if isinstance(max_per_user, int) and max_per_user > 0 and len(items) > max_per_user:
                        for fdoc, _dt in items[max_per_user:]:
                            fid = getattr(fdoc, '_id', None)
                            if fid not in cand_id_set:
                                cand_id_set.add(fid)
                                cand_ids.append(fid)
                    for fdoc, dt in items:
                        if dt < cutoff:
                            fid = getattr(fdoc, '_id', None)
                            if fid not in cand_id_set:
                                cand_id_set.add(fid)
                                cand_ids.append(fid)
                for fid in cand_ids:
                    if time.time() > deadline:
                        break
                    try:
                        if fid is not None:
                            fs.delete(fid)
                            summary["gridfs_deleted"] += 1
                    except Exception as e:
                        summary["errors"].append(f"gridfs_delete:{e}")
            except Exception as e:
                summary["errors"].append(f"gridfs_cleanup:{e}")

        return summary

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
            # בדיקת מקום פנוי לפני כתיבה
            self._maybe_alert_low_space()
            backup_id = metadata.get("backup_id") or f"backup_{int(datetime.now(timezone.utc).timestamp())}"
            # נסה להטמיע/לעדכן metadata.json בתוך ה-ZIP כך שיכלול לפחות backup_id ו-user_id אם סופק
            try:
                merged_bytes = data
                with zipfile.ZipFile(io.BytesIO(data), 'r') as zin:
                    # קרא מטאדטה קיימת אם יש
                    existing_md: Dict[str, Any] = {}
                    with suppress(Exception):
                        raw = zin.read('metadata.json')
                        try:
                            existing_md = json.loads(raw)
                        except Exception:
                            try:
                                text = raw.decode('utf-8', errors='ignore')
                                # פענוח מינימלי
                                existing_md = {}
                                bid_m = re.search(r'"backup_id"\s*:\s*"([^"]+)"', text)
                                uid_m = re.search(r'"user_id"\s*:\s*(\d+)', text)
                                if bid_m:
                                    existing_md['backup_id'] = bid_m.group(1)
                                if uid_m:
                                    existing_md['user_id'] = int(uid_m.group(1))
                            except Exception:
                                existing_md = {}
                    # מטאדטה הסופית — metadata הנכנסת גוברת
                    final_md = dict(existing_md)
                    final_md.update(metadata or {})
                    # ודא ש-backup_id קיים בתוצאה
                    final_md['backup_id'] = final_md.get('backup_id') or backup_id
                    # בנה ZIP חדש עם metadata.json מעודכן
                    out = io.BytesIO()
                    with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
                        for name in zin.namelist():
                            if name == 'metadata.json' or name.endswith('/'):
                                continue
                            try:
                                zout.writestr(name, zin.read(name))
                            except Exception:
                                continue
                        # כתוב metadata.json מעודכן
                        try:
                            zout.writestr('metadata.json', json.dumps(final_md, indent=2))
                        except Exception:
                            # fallback בלי indent
                            zout.writestr('metadata.json', json.dumps(final_md))
                    merged_bytes = out.getvalue()
                data = merged_bytes
                # עדכן backup_id אם הוכנס ב-final_md
                backup_id = (final_md.get('backup_id') or backup_id)
            except Exception:
                # אם לא הצלחנו לטפל — המשך עם הנתונים המקוריים
                pass

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
            # בדיקת מקום פנוי לפני כתיבה/העתקה
            self._maybe_alert_low_space()
            # 1) קרא מטאדטה מתוך ה‑ZIP (ללא קריאה של כל הקובץ לזיכרון)
            metadata: Dict[str, Any] = {}
            try:
                with zipfile.ZipFile(file_path, 'r') as zf:
                    with suppress(Exception):
                        md_raw = zf.read('metadata.json')
                        metadata = json.loads(md_raw) if md_raw else {}
            except Exception:
                metadata = {}

            # הפק backup_id אם חסר
            backup_id = metadata.get("backup_id") or os.path.splitext(os.path.basename(file_path))[0]
            metadata["backup_id"] = backup_id
            filename = f"{backup_id}.zip"

            # 2) שמירה לפי מצב אחסון — הימנע מקריאה מלאה של הקובץ לזיכרון
            if self.storage_mode == "mongo":
                fs = self._get_gridfs()
                if fs is None:
                    # נפילה לאחסון קבצים
                    target_path = self.backup_dir / filename
                    try:
                        # העתקה חסכונית בזיכרון
                        import shutil
                        shutil.copyfile(file_path, target_path)
                    except Exception:
                        # fallback לכתיבה בבלוקים אם shutil נכשל
                        with open(file_path, 'rb') as src, open(target_path, 'wb') as dst:
                            while True:
                                chunk = src.read(1024 * 1024)
                                if not chunk:
                                    break
                                dst.write(chunk)
                    return backup_id
                # GridFS – מחיקה של עותק קודם (בשם זהה) ושמירה בזרימה
                with suppress(Exception):
                    for fdoc in fs.find({"filename": filename}):
                        fs.delete(fdoc._id)
                with open(file_path, 'rb') as fobj:
                    fs.put(fobj, filename=filename, metadata=metadata)  # type: ignore[arg-type]
                return backup_id

            # ברירת מחדל: קבצים
            target_path = self.backup_dir / filename
            try:
                import shutil
                shutil.copyfile(file_path, target_path)
            except Exception:
                with open(file_path, 'rb') as src, open(target_path, 'wb') as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
            return backup_id
        except Exception as e:
            logger.warning(f"save_backup_file failed: {e}")
            return None

    def list_backups(self, user_id: int) -> List[BackupInfo]:
        """מחזירה רשימת קבצי ZIP ששייכים למשתמש המבקש בלבד.

        כל פריט חייב להיות מסווג כשייך ל-user_id דרך אחד מהבאים:
        - metadata.json בתוך ה-ZIP עם שדה user_id תואם
        - דפוס מזהה בשם: backup_<user_id>_*

        ZIPים ללא שיוך ברור למשתמש לא ייכללו כדי למנוע זליגת מידע.
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

            # קבצים בדיסק — מציגים רק קבצים ששייכים למשתמש
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
                        owner_user_id: Optional[int] = None
                        created_at: Optional[datetime] = None
                        file_count: int = 0
                        backup_type: str = "unknown"
                        repo: Optional[str] = None
                        path: Optional[str] = None

                        with zipfile.ZipFile(backup_file, 'r') as zf:
                            # נסה לקרוא metadata.json, אם קיים
                            try:
                                metadata_content = zf.read("metadata.json")
                                try:
                                    # json.loads תומך ב-bytes; אם ייכשל ננסה דקדוק חלופי
                                    metadata = json.loads(metadata_content)
                                except Exception:
                                    # fallback: ננסה לפענח כמחרוזת ולחלץ שדות בסיסיים ב-regex
                                    try:
                                        text = metadata_content.decode('utf-8', errors='ignore')
                                    except Exception:
                                        text = str(metadata_content)
                                    metadata = {}
                                    # backup_id
                                    try:
                                        m_bid = re.search(r'"backup_id"\s*:\s*"([^"]+)"', text)
                                        if m_bid:
                                            metadata["backup_id"] = m_bid.group(1)
                                    except Exception:
                                        pass
                                    # user_id
                                    try:
                                        m_uid = re.search(r'"user_id"\s*:\s*(\d+)', text)
                                        if m_uid:
                                            metadata["user_id"] = int(m_uid.group(1))
                                    except Exception:
                                        pass
                                    # created_at
                                    try:
                                        m_cat = re.search(r'"created_at"\s*:\s*"([^"]+)"', text)
                                        if m_cat:
                                            metadata["created_at"] = m_cat.group(1)
                                    except Exception:
                                        pass
                            except Exception:
                                metadata = None

                            # קבע בעלים של ה-ZIP מתוך metadata אם קיים
                            if metadata is not None:
                                try:
                                    uid_val = metadata.get("user_id")
                                    if isinstance(uid_val, str) and uid_val.isdigit():
                                        owner_user_id = int(uid_val)
                                    elif isinstance(uid_val, int):
                                        owner_user_id = uid_val
                                except Exception:
                                    owner_user_id = None

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

                            # אם אין owner במטאדטה — נסה להסיק משם הקובץ: backup_<user>_*
                            if owner_user_id is None:
                                try:
                                    m = re.match(r"^backup_(\d+)_", backup_id)
                                    if m:
                                        owner_user_id = int(m.group(1))
                                except Exception:
                                    owner_user_id = None

                            # סינון: הצג רק אם שייך למשתמש המבקש
                            if owner_user_id is None or owner_user_id != user_id:
                                # לא שייך למשתמש — דלג
                                continue

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
                            user_id=owner_user_id if owner_user_id is not None else user_id,
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

            # קבצים ב-GridFS (Mongo) – נטען רק של המשתמש
            try:
                fs = self._get_gridfs()
                if fs is not None:
                    # טען את כל הפריטים ובדוק בעלות בקוד כדי לכלול גם legacy ללא metadata.user_id
                    cursor = fs.find()
                    for fdoc in cursor:
                        try:
                            md = getattr(fdoc, 'metadata', None) or {}
                            # קבע backup_id מוקדם לשימושים שונים
                            backup_id = md.get("backup_id") or os.path.splitext(fdoc.filename or "")[0] or str(getattr(fdoc, "_id", ""))
                            if not backup_id:
                                continue
                            if any(b.backup_id == backup_id for b in backups):
                                # כבר קיים מתוך הדיסק
                                continue
                            total_size = int(getattr(fdoc, 'length', 0) or 0)

                            # זיהוי בעלות: metadata.user_id → דפוס בשם → metadata.json מתוך ה-ZIP
                            owner_user_id = None
                            try:
                                uid_val = md.get("user_id")
                                if isinstance(uid_val, str) and uid_val.isdigit():
                                    owner_user_id = int(uid_val)
                                elif isinstance(uid_val, int):
                                    owner_user_id = uid_val
                            except Exception:
                                owner_user_id = None
                            if owner_user_id is None:
                                try:
                                    m = re.match(r"^backup_(\d+)_", backup_id)
                                    if m:
                                        owner_user_id = int(m.group(1))
                                except Exception:
                                    owner_user_id = None
                            # אם עדיין לא ידוע — קרא metadata.json מתוך ה-ZIP המקומי
                            local_path = self.backup_dir / f"{backup_id}.zip"
                            if owner_user_id is None:
                                try:
                                    if not local_path.exists() or (total_size and local_path.stat().st_size != total_size):
                                        grid_out = fs.get(fdoc._id)
                                        with open(local_path, 'wb') as lf:
                                            lf.write(grid_out.read())
                                    with zipfile.ZipFile(local_path, 'r') as zf:
                                        with suppress(Exception):
                                            raw = zf.read('metadata.json')
                                            md2 = json.loads(raw) if raw else {}
                                            u2 = md2.get('user_id')
                                            if isinstance(u2, int):
                                                owner_user_id = u2
                                            elif isinstance(u2, str) and u2.isdigit():
                                                owner_user_id = int(u2)
                                except Exception:
                                    pass

                            # חסום פריטים שאינם שייכים למשתמש
                            if owner_user_id != user_id:
                                continue

                            # מטא נוספים
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

                            # ודא עותק מקומי זמני קיים לשימוש בהורדה/שחזור
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
                                user_id=owner_user_id if owner_user_id is not None else user_id,
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

            # אם לא נמצאו כלל גיבויים למשתמש — אפשר מצב תאימות רכה עבור אדמין/דגל ENV
            try:
                allow_legacy = False
                # אדמין? (לפי ENV ADMIN_USER_IDS)
                try:
                    admins_raw = os.getenv("ADMIN_USER_IDS", "")
                    if admins_raw:
                        admin_ids = {int(x.strip()) for x in admins_raw.split(',') if x.strip().isdigit()}
                        if int(user_id) in admin_ids:
                            allow_legacy = True
                except Exception:
                    pass
                # או דגל תאימות ייעודי
                if not allow_legacy:
                    flag = str(os.getenv("BACKUPS_SHOW_ALL_IF_EMPTY", "")).strip().lower()
                    allow_legacy = flag in ("1", "true", "yes", "on")
            except Exception:
                allow_legacy = False

            if allow_legacy and not backups:
                try:
                    # בטעינת תאימות: הצג את כל קבצי ה‑ZIP מכל הנתיבים הידועים, גם ללא user_id מפורש.
                    # מיפוי נתיבים ייחודי למניעת כפילויות
                    seen_paths_all: Set[str] = set()
                    # build search_dirs כמו קודם
                    search_dirs_legacy: List[Path] = [self.backup_dir]
                    with suppress(Exception):
                        if getattr(self, "legacy_backup_dir", None) and isinstance(self.legacy_backup_dir, Path) and self.legacy_backup_dir.exists():
                            search_dirs_legacy.append(self.legacy_backup_dir)
                    with suppress(Exception):
                        app_backups = Path("/app/backups")
                        if app_backups != self.backup_dir and app_backups.exists():
                            search_dirs_legacy.append(app_backups)
                    for d in search_dirs_legacy:
                        with suppress(Exception):
                            for p in d.glob("*.zip"):
                                try:
                                    rp = str(p.resolve())
                                except Exception:
                                    rp = str(p)
                                if rp in seen_paths_all:
                                    continue
                                seen_paths_all.add(rp)
                                # נסה לקרוא metadata.json — אך אל תדרוש user_id
                                metadata: Optional[Dict[str, Any]] = None
                                backup_id = os.path.splitext(os.path.basename(p))[0]
                                created_at = None
                                file_count = 0
                                backup_type = "unknown"
                                repo = None
                                path = None
                                with suppress(Exception):
                                    with zipfile.ZipFile(p, 'r') as zf:
                                        with suppress(Exception):
                                            md_raw = zf.read('metadata.json')
                                            metadata = json.loads(md_raw) if md_raw else None
                                        # שדות עזר אם קיימים
                                        if metadata:
                                            with suppress(Exception):
                                                bid = metadata.get('backup_id')
                                                if isinstance(bid, str) and bid:
                                                    backup_id = bid
                                            with suppress(Exception):
                                                cat = metadata.get('created_at')
                                                if isinstance(cat, str) and cat:
                                                    created_at = datetime.fromisoformat(cat)
                                                    if created_at.tzinfo is None:
                                                        created_at = created_at.replace(tzinfo=timezone.utc)
                                            with suppress(Exception):
                                                fc = metadata.get('file_count')
                                                if isinstance(fc, int):
                                                    file_count = fc
                                            with suppress(Exception):
                                                backup_type = metadata.get('backup_type', backup_type)
                                            with suppress(Exception):
                                                repo = metadata.get('repo')
                                            with suppress(Exception):
                                                path = metadata.get('path')
                                        # אם לא קיים file_count — חשב
                                        if file_count == 0:
                                            try:
                                                non_dirs = [n for n in zf.namelist() if not n.endswith('/')]
                                                file_count = len(non_dirs)
                                            except Exception:
                                                file_count = 0
                                if not created_at:
                                    with suppress(Exception):
                                        created_at = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                                try:
                                    total_size = p.stat().st_size
                                except Exception:
                                    total_size = 0
                                # ודא שייכות למשתמש גם במצב תאימות: מטאדטה או דפוס שם המכיל את המזהה
                                owner_ok = False
                                try:
                                    if metadata is not None:
                                        u = metadata.get('user_id')
                                        if isinstance(u, int) and int(u) == int(user_id):
                                            owner_ok = True
                                        elif isinstance(u, str) and u.isdigit() and int(u) == int(user_id):
                                            owner_ok = True
                                except Exception:
                                    owner_ok = False
                                if not owner_ok:
                                    try:
                                        base = os.path.splitext(os.path.basename(p))[0]
                                        # חפש את user_id כמילה/חלק מופרד בקו תחתון
                                        m = re.search(rf"(?:^|_)({int(user_id)})($|_|\b)", base)
                                        if m:
                                            owner_ok = True
                                    except Exception:
                                        owner_ok = False
                                if not owner_ok:
                                    # ללא הוכחת בעלות — אל תציג כדי למנוע זליגה
                                    continue

                                backups.append(BackupInfo(
                                    backup_id=backup_id,
                                    user_id=int(user_id),
                                    created_at=created_at or datetime.now(timezone.utc),
                                    file_count=file_count,
                                    total_size=total_size,
                                    backup_type=backup_type,
                                    status="completed",
                                    file_path=rp,
                                    repo=repo,
                                    path=path,
                                    metadata=metadata,
                                ))
                except Exception:
                    # תאימות לאחור היא best-effort בלבד
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
                    existing = db.get_user_files(user_id, limit=1000, projection={"file_name": 1}) or []
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
                        # אם יש תגית repo:* — הוסף אותה רק עבור קבצים שנמצאים בשורש הריפו או תחת נתיב התואם לריפו
                        filtered_extra = list(extra_tags or [])
                        try:
                            repo_tags = [t for t in filtered_extra if isinstance(t, str) and t.strip().lower().startswith('repo:')]
                            # כלל זהיר: שמור את תג ה-repo רק אם הנתיב אינו כולל סלאשים רבים/או שהקובץ בשם שאינו גורף (index.html יכול להופיע בכל מקום) —
                            # בפשטות: תמיד נאפשר, אבל נוסיף רק את תג ה-repo האחרון (אם קיים) והיתר נסנן למעלה בשכבת repo.save_file
                            if repo_tags:
                                filtered_extra = [repo_tags[-1]] + [t for t in filtered_extra if not (isinstance(t, str) and t.strip().lower().startswith('repo:'))]
                        except Exception:
                            pass
                        ok = db.save_file(user_id=user_id, file_name=name, code=text, programming_language=lang, extra_tags=filtered_extra)
                        if ok:
                            results["restored_files"] += 1
                        else:
                            results["errors"].append(f"save failed for {name}")
                    except Exception as e:
                        results["errors"].append(f"restore failed for {name}: {e}")
        except Exception as e:
            results["errors"].append(str(e))
        return results

    def delete_backups(self, user_id: int, backup_ids: List[str]) -> Dict[str, Any]:
        """מוחק מספר גיבויי ZIP לפי backup_id ממערכת הקבצים ומ-GridFS (אם בשימוש).

        החזרה: {"deleted": int, "errors": [str, ...]}
        """
        results: Dict[str, Any] = {"deleted": 0, "errors": []}
        try:
            if not backup_ids:
                return results
            filenames = [f"{bid}.zip" for bid in backup_ids]

            # מחיקה ממערכת הקבצים (כולל נתיבי legacy)
            search_dirs: List[Path] = [self.backup_dir]
            try:
                if getattr(self, "legacy_backup_dir", None):
                    if isinstance(self.legacy_backup_dir, Path):
                        search_dirs.append(self.legacy_backup_dir)
            except Exception:
                pass
            try:
                app_backups = Path("/app/backups")
                if app_backups != self.backup_dir:
                    search_dirs.append(app_backups)
            except Exception:
                pass

            deleted_fs = 0
            for d in search_dirs:
                for fn in filenames:
                    try:
                        p = d / fn
                        if p.exists():
                            # בדוק שיוך משתמש אם יש metadata.json
                            try:
                                with zipfile.ZipFile(p, 'r') as zf:
                                    md = None
                                    with suppress(Exception):
                                        raw = zf.read('metadata.json')
                                        md = json.loads(raw) if raw else None
                                    if md and md.get('user_id') is not None and md.get('user_id') != user_id:
                                        # שייך למשתמש אחר — דלג
                                        continue
                            except Exception:
                                pass
                            p.unlink()
                            deleted_fs += 1
                    except Exception as e:
                        results["errors"].append(f"fs:{fn}:{e}")

            # מחיקה מ-GridFS (אם קיים)
            fs = None
            try:
                fs = self._get_gridfs()
            except Exception:
                fs = None
            if fs is not None:
                for bid, fn in zip(backup_ids, filenames):
                    try:
                        # שלוף מועמדים לפי filename/backup_id ללא סינון על user_id כדי לא לפספס legacy
                        candidates = []
                        with suppress(Exception):
                            candidates.extend(list(fs.find({"filename": fn})))
                        with suppress(Exception):
                            candidates.extend(list(fs.find({"metadata.backup_id": bid})))
                        seen = set()
                        for fdoc in candidates:
                            try:
                                if getattr(fdoc, '_id', None) in seen:
                                    continue
                                seen.add(getattr(fdoc, '_id', None))
                                md = getattr(fdoc, 'metadata', None) or {}
                                owner_ok = False
                                # 1) metadata.user_id כמספר או מחרוזת
                                uid_val = md.get('user_id')
                                if isinstance(uid_val, int) and uid_val == user_id:
                                    owner_ok = True
                                elif isinstance(uid_val, str) and uid_val.isdigit() and int(uid_val) == user_id:
                                    owner_ok = True
                                # 2) גיבוי לפי דפוס backup_<user>_* בשם הקובץ
                                if not owner_ok:
                                    try:
                                        base = os.path.splitext(str(getattr(fdoc, 'filename', '') or ''))[0]
                                        m = re.match(r"^backup_(\d+)_", base)
                                        if m and int(m.group(1)) == user_id:
                                            owner_ok = True
                                    except Exception:
                                        pass
                                # 3) כמוצא אחרון: אם יש עותק מקומי — פתח וקרא metadata.json לאימות
                                if not owner_ok:
                                    try:
                                        local_path = self.backup_dir / f"{bid}.zip"
                                        if not local_path.exists():
                                            grid_out = fs.get(fdoc._id)
                                            with open(local_path, 'wb') as lf:
                                                lf.write(grid_out.read())
                                        with zipfile.ZipFile(local_path, 'r') as zf:
                                            with suppress(Exception):
                                                raw = zf.read('metadata.json')
                                                md2 = json.loads(raw) if raw else {}
                                                u2 = md2.get('user_id')
                                                if (isinstance(u2, int) and u2 == user_id) or (isinstance(u2, str) and u2.isdigit() and int(u2) == user_id):
                                                    owner_ok = True
                                    except Exception:
                                        pass
                                if owner_ok:
                                    fs.delete(fdoc._id)
                                    results["deleted"] += 1
                            except Exception:
                                continue
                    except Exception as e:
                        results["errors"].append(f"gridfs:{fn}:{e}")

            # אם אין GridFS — ספר מחיקות FS
            if fs is None:
                results["deleted"] += deleted_fs

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