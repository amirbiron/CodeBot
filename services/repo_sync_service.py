"""
Repository Sync Service

ניהול סנכרון הריפו:
- Initial import
- Delta sync (מ-webhook)
- Manual sync

**חשוב לגבי Gunicorn Multi-Workers:**
ב-Render (ובכל סביבת פרודקשן), gunicorn מריץ מספר workers (processes).
כל worker הוא process נפרד עם זיכרון נפרד!

בעיה: אם משתמשים ב-Queue/Dict בזיכרון:
- Webhook מגיע ל-Worker A -> Job נשמר בזיכרון של A
- User עושה refresh -> מגיע ל-Worker B -> "Job not found" (404)

פתרונות:
1. **MongoDB-based Queue** (מומלץ) - Jobs נשמרים ב-DB, כל worker יכול לראות
2. **WEB_CONCURRENCY=1** - worker בודד (פשוט אבל לא scalable)
3. **Redis + Celery** - פתרון enterprise (מורכב יותר)

הקוד הזה משתמש ב-MongoDB-based Queue.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

# חשוב! ReturnDocument הוא Enum, לא בוליאני
from pymongo import ReturnDocument
from pymongo.errors import (  # type: ignore
    AutoReconnect,
    ConnectionFailure,
    NetworkTimeout,
    NotPrimaryError,
    PrimarySteppedDown,
    ServerSelectionTimeoutError,
)
from tenacity import (  # type: ignore
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from services.code_indexer import CodeIndexer
from services.git_mirror_service import get_mirror_service

logger = logging.getLogger(__name__)

# Flag לוודא worker אחד per process
_worker_started = False
_worker_lock = threading.Lock()

_RETRYABLE_MONGO_ERRORS = (
    ServerSelectionTimeoutError,
    AutoReconnect,
    NotPrimaryError,
    PrimarySteppedDown,
    ConnectionFailure,
    NetworkTimeout,
)


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.5, max=4.0),
    retry=retry_if_exception_type(_RETRYABLE_MONGO_ERRORS),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _find_next_job_with_retry(db: Any) -> Optional[Dict[str, Any]]:
    """תפיסת job בצורה אטומית, עם retry עדין בזמן failover/election של Mongo."""
    return db.sync_jobs.find_one_and_update(
        {"status": "pending"},
        {"$set": {"status": "running", "started_at": datetime.utcnow()}},
        sort=[("created_at", 1)],  # FIFO - הישן קודם
        return_document=ReturnDocument.AFTER,  # מחזיר את המסמך אחרי העדכון
    )


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.5, max=4.0),
    retry=retry_if_exception_type(_RETRYABLE_MONGO_ERRORS),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
def _update_job_with_retry(db: Any, job_id: str, update_doc: Dict[str, Any]) -> None:
    db.sync_jobs.update_one({"_id": job_id}, update_doc)


def trigger_sync(
    repo_name: str,
    new_sha: str,
    old_sha: Optional[str] = None,
    trigger: str = "webhook",
    delivery_id: Optional[str] = None,
) -> str:
    """
    הפעלת סנכרון ברקע - שומר ב-MongoDB

    Args:
        repo_name: שם הריפו
        new_sha: SHA החדש
        old_sha: SHA הישן (אופציונלי)
        trigger: מקור ההפעלה
        delivery_id: מזהה ייחודי

    Returns:
        job_id
    """
    from database.db_manager import get_db

    job_id = delivery_id or str(uuid.uuid4())[:8]

    # שמירת Job ב-MongoDB (לא בזיכרון!)
    db = get_db()

    job_doc = {
        "_id": job_id,
        "repo_name": repo_name,
        "new_sha": new_sha,
        "old_sha": old_sha,
        "trigger": trigger,
        "status": "pending",
        "created_at": datetime.utcnow(),
        "started_at": None,
        "completed_at": None,
        "result": None,
        "error": None,
        # TTL index - מחיקה אוטומטית אחרי 7 ימים
        "expire_at": datetime.utcnow() + timedelta(days=7),
    }

    # Upsert - אם אותו delivery_id כבר קיים, לא ליצור כפילות
    db.sync_jobs.update_one({"_id": job_id}, {"$setOnInsert": job_doc}, upsert=True)

    logger.info(f"Sync job queued in MongoDB: {job_id}")

    # הפעלת worker (אם לא רץ)
    _ensure_worker_started()

    return job_id


def get_job_status(job_id: str) -> Optional[Dict[str, Any]]:
    """קבלת סטטוס משימה מ-MongoDB"""
    from database.db_manager import get_db

    db = get_db()
    job = db.sync_jobs.find_one({"_id": job_id})

    if not job:
        return None

    return {
        "job_id": job["_id"],
        "status": job["status"],
        "repo": job["repo_name"],
        "trigger": job["trigger"],
        "created_at": job["created_at"].isoformat() if job.get("created_at") else None,
        "started_at": job["started_at"].isoformat() if job.get("started_at") else None,
        "completed_at": job["completed_at"].isoformat() if job.get("completed_at") else None,
        "result": job.get("result"),
        "error": job.get("error"),
    }


def _ensure_worker_started() -> None:
    """הפעלת worker thread אם לא פעיל (per process)"""
    global _worker_started

    with _worker_lock:
        if not _worker_started:
            worker = threading.Thread(target=_sync_worker, daemon=True)
            worker.start()
            _worker_started = True
            logger.info("Sync worker thread started")


def _sync_worker() -> None:
    """
    Worker thread - polling על MongoDB לחיפוש jobs

    Note: כל Gunicorn worker יריץ את ה-thread הזה.
    השימוש ב-findOneAndUpdate עם "$set": {"status": "running"}
    מבטיח שרק worker אחד יתפוס כל job (atomic operation).
    """
    from database.db_manager import get_db

    logger.info("Sync worker polling MongoDB...")

    while True:
        try:
            db = get_db()

            # Atomic: מצא job pending ותפוס אותו
            # חשוב: return_document הוא Enum ב-PyMongo, לא True/False!
            job = _find_next_job_with_retry(db)

            if not job:
                # אין jobs - ישן 5 שניות
                time.sleep(5)
                continue

            job_id = job["_id"]
            logger.info(f"Processing sync job: {job_id}")

            try:
                result = _run_sync_from_doc(job, db)

                # עדכון סטטוס - completed
                _update_job_with_retry(
                    db,
                    job_id,
                    {"$set": {"status": "completed", "completed_at": datetime.utcnow(), "result": result}},
                )

                logger.info(f"Job {job_id} completed successfully")

            except Exception as e:
                logger.exception(f"Sync job failed: {job_id}")

                # עדכון סטטוס - failed
                try:
                    _update_job_with_retry(
                        db,
                        job_id,
                        {"$set": {"status": "failed", "completed_at": datetime.utcnow(), "error": str(e)}},
                    )
                except Exception:
                    # אם אפילו עדכון הסטטוס נכשל (למשל בזמן failover), אל תפיל את ה-thread
                    logger.exception("Failed to update failed status for job %s", job_id)

        except Exception as e:
            logger.exception(f"Worker error: {e}")
            time.sleep(10)  # backoff on error


def _run_sync_from_doc(job_doc: Dict[str, Any], db: Any) -> Dict[str, Any]:
    """
    הרצת סנכרון מ-document של MongoDB

    Args:
        job_doc: document מ-sync_jobs collection
        db: חיבור ל-MongoDB

    Returns:
        תוצאות הסנכרון
    """
    git_service = get_mirror_service()
    indexer = CodeIndexer(db)

    repo_name = job_doc["repo_name"]
    new_sha = job_doc["new_sha"]
    old_sha = job_doc.get("old_sha")

    # המשך הלוגיקה כמו ב-_run_sync המקורי...
    return _run_sync_logic(git_service, indexer, db, repo_name, new_sha, old_sha)


def _run_sync_logic(
    git_service: Any,
    indexer: CodeIndexer,
    db: Any,
    repo_name: str,
    new_sha: str,
    old_sha: Optional[str],
) -> Dict[str, Any]:
    """הלוגיקה של הסנכרון - מופרדת לשימוש חוזר"""

    # וידוא שה-mirror קיים
    if not git_service.mirror_exists(repo_name):
        return {"error": "Mirror not found. Run initial import first."}

    # Fetch עדכונים
    fetch_result = git_service.fetch_updates(repo_name)
    if not fetch_result["success"]:
        return {"error": "Fetch failed", "details": fetch_result}

    # אם אין old_sha, נשלוף מה-DB
    if not old_sha:
        metadata = db.repo_metadata.find_one({"repo_name": repo_name})
        old_sha = metadata.get("last_synced_sha") if metadata else None

    if not old_sha:
        return {"error": "No previous SHA. Run initial import first."}

    # אם ה-SHA זהה, אין מה לעדכן
    if old_sha == new_sha:
        return {"status": "up_to_date", "message": "No changes"}

    # קבלת רשימת שינויים
    changes = git_service.get_changed_files(repo_name, old_sha, new_sha)

    if changes is None:
        return {"error": "Failed to get changed files"}

    stats = {"added": 0, "modified": 0, "removed": 0, "renamed": 0, "indexed": 0, "skipped": 0, "errors": 0}

    # מחיקת קבצים שנמחקו
    if changes["removed"]:
        removed_count = indexer.remove_files(repo_name, changes["removed"])
        stats["removed"] = removed_count
        logger.info(f"Removed {removed_count} files from index")

    # טיפול ב-RENAMED files (חשוב!)
    # git diff-tree עם -M מחזיר סטטוס R לקבצים ששונו שם
    files_to_process = changes["added"] + changes["modified"]

    if changes.get("renamed"):
        for rename_info in changes["renamed"]:
            old_path = rename_info["old"]
            new_path = rename_info["new"]

            # 1. מחיקת הקובץ הישן מהאינדקס
            indexer.remove_file(repo_name, old_path)

            # 2. הוספת הקובץ החדש לרשימת העיבוד רק אם הוא רלוונטי לאינדקס
            if indexer.should_index(new_path):
                files_to_process.append(new_path)
                stats["renamed"] += 1

            logger.debug(f"Renamed: {old_path} -> {new_path}")

    # עדכון/הוספת קבצים
    for file_path in files_to_process:
        if not indexer.should_index(file_path):
            stats["skipped"] += 1
            continue

        content = git_service.get_file_content(repo_name, file_path, new_sha)

        # תוכן ריק "" הוא תקין; רק None אומר שהקריאה נכשלה/אין קובץ
        if content is not None:
            if indexer.index_file(repo_name, file_path, content, new_sha):
                stats["indexed"] += 1
                if file_path in changes["added"]:
                    stats["added"] += 1
                elif file_path in changes["modified"]:
                    stats["modified"] += 1
            else:
                stats["errors"] += 1
        else:
            stats["errors"] += 1
            logger.warning(f"Skipping file content for {file_path} (unable to read)")

    # עדכון metadata
    db.repo_metadata.update_one(
        {"repo_name": repo_name},
        {
            "$set": {
                "last_synced_sha": new_sha,
                "last_sync_time": datetime.utcnow(),
                "sync_status": "completed",
                "last_sync_stats": stats,
            }
        },
        upsert=True,
    )

    logger.info(f"Sync completed: {stats}")

    return {"status": "synced", "old_sha": old_sha[:7], "new_sha": new_sha[:7], "stats": stats}


def initial_import(repo_url: str, repo_name: str, db: Any) -> Dict[str, Any]:
    """
    ייבוא ראשוני של ריפו

    Args:
        repo_url: URL של הריפו
        repo_name: שם הריפו
        db: חיבור ל-MongoDB

    Returns:
        תוצאות הייבוא
    """
    git_service = get_mirror_service()
    indexer = CodeIndexer(db)

    logger.info(f"Starting initial import: {repo_url}")

    # 1. יצירת mirror
    result = git_service.init_mirror(repo_url, repo_name)

    if not result["success"]:
        return {"error": "Failed to create mirror", "details": result}

    repo_path = git_service._get_repo_path(repo_name)

    # 2. זיהוי ה-Default Branch האמיתי
    # ב-Mirror, HEAD מצביע על ה-default branch של origin
    def _strip_origin_prefix(ref: str) -> str:
        ref = str(ref or "").strip()
        if ref.startswith("refs/remotes/origin/"):
            return ref[len("refs/remotes/origin/"):]
        if ref.startswith("origin/"):
            return ref.split("/", 1)[1]
        return ref

    def _ref_exists(ref: str) -> bool:
        result = git_service._run_git_command(
            ["git", "show-ref", "--verify", "--quiet", ref],
            cwd=repo_path,
        )
        return result.success

    def _branch_exists(branch: str) -> bool:
        if not branch:
            return False
        return _ref_exists(f"refs/heads/{branch}") or _ref_exists(f"refs/remotes/origin/{branch}")
    default_branch = ""
    branch_result = git_service._run_git_command(["git", "symbolic-ref", "--short", "HEAD"], cwd=repo_path)
    if branch_result.success:
        default_branch = _strip_origin_prefix(branch_result.stdout.strip())
        if not _branch_exists(default_branch):
            logger.info(f"HEAD pointed to missing branch: {default_branch}")
            default_branch = ""

    # אם HEAD לא תקין, נסה origin/HEAD (נוצר ב-mirror)
    if not default_branch:
        head_result = git_service._run_git_command(
            ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
            cwd=repo_path,
        )
        if head_result.success:
            default_branch = _strip_origin_prefix(head_result.stdout.strip())
            if not _branch_exists(default_branch):
                logger.info(f"origin/HEAD pointed to missing branch: {default_branch}")
                default_branch = ""

    # Fallback: בחר ברנץ' ראשון מ-origin (עדיף main/master)
    if not default_branch:
        refs_result = git_service._run_git_command(
            ["git", "for-each-ref", "--format=%(refname)", "refs/remotes/origin"],
            cwd=repo_path,
        )
        refs = [r.strip() for r in (refs_result.stdout or "").splitlines() if r.strip()]
        preferred = (
            next((r for r in refs if r.endswith("/main")), "")
            or next((r for r in refs if r.endswith("/master")), "")
        )
        if not preferred:
            preferred = next((r for r in refs if not r.endswith("/HEAD")), "")
        default_branch = _strip_origin_prefix(preferred)

    # Fallback 2: ב-mirror אין refs/remotes/origin - חפש ישירות ב-refs/heads
    if not default_branch:
        logger.info("No refs/remotes/origin found, checking refs/heads directly (mirror mode)")
        refs_result = git_service._run_git_command(
            ["git", "for-each-ref", "--format=%(refname)", "refs/heads"],
            cwd=repo_path,
        )
        refs = [r.strip() for r in (refs_result.stdout or "").splitlines() if r.strip()]
        logger.info(f"Available refs/heads: {refs}")
        preferred = (
            next((r for r in refs if r.endswith("/main")), "")
            or next((r for r in refs if r.endswith("/master")), "")
        )
        if not preferred:
            preferred = next((r for r in refs if r.strip()), "")
        if preferred:
            # refs/heads/main -> main
            default_branch = preferred.replace("refs/heads/", "")
            logger.info(f"Found branch in refs/heads: {default_branch}")

    if not default_branch:
        logger.warning("Could not detect any branch, falling back to 'main'")
        default_branch = "main"

    logger.info(f"Detected default branch: {default_branch}")

    # 3. רשימת כל הקבצים
    # ב-mirror, ה-refs יכולים להיות תחת refs/remotes/origin/<branch>.
    # ננסה כמה אפשרויות לפי סדר עדיפות ונשתמש בראשון שעובד.
    tree_ref_candidates = [
        f"refs/heads/{default_branch}",
        f"refs/remotes/origin/{default_branch}",
        f"origin/{default_branch}",
        default_branch,
    ]
    all_files = None
    tree_ref = ""
    for candidate in tree_ref_candidates:
        all_files = git_service.list_all_files(repo_name, ref=candidate)
        if all_files is not None:
            tree_ref = candidate
            break
    if all_files is None:
        logger.error(
            f"Failed to list files for {repo_name} at refs: {', '.join(tree_ref_candidates)}"
        )
        return {
            "error": "Failed to list repository files",
            "details": "Check if branch ref exists or mirror repo is corrupt",
            "repo_name": repo_name,
            "ref": ", ".join(tree_ref_candidates),
        }

    # 3. סינון קבצי קוד
    code_files = [f for f in all_files if indexer.should_index(f)]

    logger.info(f"Found {len(code_files)} code files out of {len(all_files)} total")

    # 4. אינדוקס
    indexed_count = 0
    error_count = 0

    # שימוש ב-default_branch שזיהינו — חייב להיות SHA סטטי (לא "HEAD" סמלי)
    current_sha = git_service.get_current_sha(repo_name, branch=default_branch)
    if not current_sha:
        # ניסיון אחרון: לפתור SHA ישירות מה-ref של העץ
        sha_res = git_service._run_git_command(["git", "rev-parse", tree_ref], cwd=repo_path, timeout=10)
        if sha_res.success and sha_res.stdout.strip():
            current_sha = sha_res.stdout.strip()
    if not current_sha:
        # ניסיון אחרון: לפתור SHA מה-HEAD הנוכחי, אבל לשמור את ההאש עצמו (לא את המחרוזת HEAD)
        sha_res = git_service._run_git_command(["git", "rev-parse", "HEAD"], cwd=repo_path, timeout=10)
        if sha_res.success and sha_res.stdout.strip():
            current_sha = sha_res.stdout.strip()
    if not current_sha:
        logger.error(f"Could not resolve commit SHA for {repo_name} (branch={default_branch})")
        return {
            "error": "Could not resolve commit SHA",
            "details": "Import failed (unable to resolve a stable commit SHA)",
            "repo_name": repo_name,
            "branch": default_branch,
            "ref": tree_ref,
        }

    # הכנת ה-ref לשליפת תוכן
    # חשוב! חייבים להשתמש באותו ref כמו ב-list_all_files
    # אחרת נשלוף תוכן מ-HEAD שיכול להיות שונה
    content_ref = tree_ref

    for i, file_path in enumerate(code_files):
        if i % 100 == 0:
            logger.info(f"Indexing progress: {i}/{len(code_files)}")

        # התיקון: מעבירים ref במפורש (לא HEAD!)
        content = git_service.get_file_content(repo_name, file_path, ref=content_ref)

        # תוכן ריק "" הוא תקין; רק None אומר שהקריאה נכשלה/אין קובץ
        if content is not None:
            if indexer.index_file(repo_name, file_path, content, current_sha):
                indexed_count += 1
            else:
                error_count += 1
        else:
            error_count += 1
            logger.warning(f"Skipping file content for {file_path} (unable to read)")

    # 5. שמירת metadata (כולל default_branch לשימוש בחיפוש ובסנכרון)
    db.repo_metadata.update_one(
        {"repo_name": repo_name},
        {
            "$set": {
                "repo_url": repo_url,
                "default_branch": default_branch,  # חשוב! לשימוש ב-git grep וב-sync
                "last_synced_sha": current_sha,
                "last_sync_time": datetime.utcnow(),
                "total_files": len(code_files),
                "sync_status": "completed",
                "initial_import": True,
            }
        },
        upsert=True,
    )

    logger.info(f"Initial import completed: {indexed_count} files indexed")

    return {
        "status": "completed",
        # עקביות מול מה שנשמר ב-MongoDB: total_files = מספר הקבצים שבחרנו לאנדקס (code_files)
        "total_files": len(code_files),
        # שדה נוסף למספר כל הקבצים בריפו (כולל לא-מאונדקסים)
        "total_git_files": len(all_files),
        "code_files": len(code_files),
        "indexed": indexed_count,
        "errors": error_count,
        "sha": current_sha[:7],
    }

