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
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

# חשוב! ReturnDocument הוא Enum, לא בוליאני
from pymongo import ReturnDocument
from pymongo.errors import (  # type: ignore
    AutoReconnect,
    ConnectionFailure,
    NetworkTimeout,
    NotPrimaryError,
    PyMongoError,
    ServerSelectionTimeoutError,
)

# תאימות בין גרסאות PyMongo: בחלק מהגרסאות אין PrimarySteppedDown.
try:  # pragma: no cover
    from pymongo.errors import PrimarySteppedDown as _PrimarySteppedDown  # type: ignore
except Exception:  # pragma: no cover
    _PrimarySteppedDown = NotPrimaryError  # type: ignore[misc,assignment]
from tenacity import (  # type: ignore
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from services.code_indexer import CodeIndexer
from services.git_mirror_service import get_mirror_service
from services.repo_mirror_fill import (
    CLONE_CLONED,
    CLONE_EXISTS,
    CLONE_NO_URL,
    clone_if_missing,
    read_repo_record,
    read_repo_records,
    redact,
)

logger = logging.getLogger(__name__)

# Flag לוודא worker אחד per process
_worker_started = False
_worker_lock = threading.Lock()

_RETRYABLE_MONGO_ERRORS = (
    ServerSelectionTimeoutError,
    AutoReconnect,
    NotPrimaryError,
    _PrimarySteppedDown,
    ConnectionFailure,
    NetworkTimeout,
)

# ---- התוצאה של סנכרון, והסטטוס שהיא נותנת לג'וב ----------------------------
#
# **כל תוצאה של ``_run_sync_logic`` נושאת ``status`` מפורש**, וה-worker קובע את הסטטוס הסופי של הג'וב לפיו
# (:func:`_job_status_for`). עד אוקטובר 2026 ארבעה מצבי כשל חזרו כ-``{"error": ...}`` בלי ``status``, וה-worker
# סימן ``completed`` כל ג'וב שלא נזרקה בו חריגה: ג'וב שלא מצא mirror, שה-fetch שלו נכשל, שאין לו SHA קודם או
# שלא קיבל את רשימת השינויים נראה בדיוק כמו ג'וב שהצליח (K11 — כשל שמדווח בערך ההחזרה ואיש לא בודק אותו).

RESULT_SYNCED = "synced"
RESULT_UP_TO_DATE = "up_to_date"
RESULT_SKIPPED = "skipped"
RESULT_FAILED = "failed"

#: הסיבות של ``RESULT_FAILED``. הסיבה היא גם ה-``error`` שנכתב לג'וב, והתוצאה המלאה נשמרת ב-``result``.
FAIL_MIRROR_MISSING = "mirror_missing"
FAIL_FETCH = "fetch_failed"
FAIL_NO_PREVIOUS_SHA = "no_previous_sha"
FAIL_CHANGES_UNAVAILABLE = "changes_unavailable"
FAIL_BASE_MOVED = "base_moved"

#: הסיבה של ``RESULT_SKIPPED``: push לריפו שאין לו רשומה ב-``repo_metadata`` — הוסר (``unmirror_repo``), וה-webhook
#: שלו נשאר מוגדר ב-GitHub. אין כאן מה לסנכרן, וזה לא כשל — ``failed`` שמור לג'וב שהיה צריך לרוץ ולא רץ.
SKIP_NOT_TRACKED = "not_tracked"

#: הסטטוסים הסופיים של ג'וב ב-``sync_jobs`` (לפניהם ``pending`` ו-``running``). הקורא היחיד של הסטטוס מחוץ לקובץ
#: הזה הוא שירות ה-MCP, שמחפש ``running`` בלבד (``mcp_server/repo_backend.py``).
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_SKIPPED = "skipped"


def _sync_failure(reason: str, message: str, **extra: Any) -> Dict[str, Any]:
    """תוצאת כשל: ``status`` ו-``reason`` למכונה, ``error`` לאדם, ופרטים נוספים כמו שהם."""
    return {"status": RESULT_FAILED, "reason": reason, "error": message, **extra}


def _job_status_for(result: Any) -> Tuple[str, Optional[str]]:
    """הסטטוס הסופי של הג'וב וה-``error`` שלו, לפי התוצאה של ``_run_sync_logic``.

    תוצאה שאינה מוכרת — לא מילון, או ``status`` שאינו אחד מ-``RESULT_*`` — היא ``failed``: באג שמחזיר צורה חדשה
    לא יסומן שוב בשקט כהצלחה.
    """
    status = result.get("status") if isinstance(result, dict) else None
    if status in (RESULT_SYNCED, RESULT_UP_TO_DATE):
        return JOB_COMPLETED, None
    if status == RESULT_SKIPPED:
        return JOB_SKIPPED, None
    if status == RESULT_FAILED:
        return JOB_FAILED, str(result.get("reason") or "unknown")
    return JOB_FAILED, "unrecognized_result"

def _count_indexed_files(db: Any, repo_name: str) -> Optional[int]:
    """כמה קבצים של הריפו נמצאים באינדקס, או ``None`` אם הספירה נכשלה.

    **זו ההגדרה היחידה של ``total_files``**, ושני מסלולי הכתיבה (הייבוא
    הראשוני והסנכרון) קוראים לה. קודם לכן הייבוא שמר ``len(code_files)``
    — הקבצים שנבחרו לאינדוקס, כולל כאלה שהאינדוקס שלהם נכשל — והסנכרון
    שמר ספירה אמיתית. ריפו שהייבוא שלו נתקל בשגיאות היה מציג מספר אחד,
    ואחרי הסנכרון הראשון קופץ למספר אחר בלי ששום קובץ השתנה.

    ``None`` נבדל מאפס בכוונה: ספירה שנכשלה אינה עדות שאין קבצים, והקורא
    משאיר את הערך הקודם במקום לכתוב "0 files" על ריפו מלא.
    """
    try:
        raw = db.repo_files.count_documents({"repo_name": repo_name})
    except PyMongoError:
        # תקלת מסד — הערך הקודם נשאר, והסנכרון הבא יתקן.
        logger.warning("Failed to count repo_files for %s; total_files left unchanged", repo_name)
        return None

    try:
        return int(raw)
    except (TypeError, ValueError):
        # **זה אינו תקלת מסד אלא באג.** ``count_documents`` שמחזיר משהו
        # שאינו מספר פירושו אדפטר שבור או סטאב שגוי, ולכן הוא נרשם ברמת
        # ``error`` ולא נבלע יחד עם תקלות רשת חולפות.
        logger.error("count_documents returned a non-numeric value for %s: %r", repo_name, raw)
        return None


def _claim_next_job(db: Any) -> Optional[Dict[str, Any]]:
    """תפיסת job בצורה אטומית ללא retry חיצוני.

    חשוב: לא עושים retry סביב find_one_and_update (לא idempotent).
    אם השרת ביצע את הכתיבה אבל הלקוח איבד את התשובה (AutoReconnect/NetworkTimeout),
    retry נוסף עלול לתפוס job נוסף ולהשאיר את הראשון תקוע ב-running.

    כדי לצמצם את הסיכון ל-job "תקוע" במקרה של תשובה שאבדה, אנחנו כותבים claim_id
    ייחודי, ואם הייתה שגיאת תשתית ננסה לאתר את ה-job לפי claim_id (קריאה היא idempotent).
    """
    claim_id = str(uuid.uuid4())
    now = datetime.utcnow()
    try:
        return db.sync_jobs.find_one_and_update(
            {"status": "pending"},
            {"$set": {"status": "running", "started_at": now, "claim_id": claim_id}},
            sort=[("created_at", 1)],  # FIFO - הישן קודם
            return_document=ReturnDocument.AFTER,  # מחזיר את המסמך אחרי העדכון
        )
    except _RETRYABLE_MONGO_ERRORS:
        # ייתכן שהכתיבה הושלמה אבל לא קיבלנו תשובה; ננסה לשחזר לפי claim_id.
        try:
            return db.sync_jobs.find_one({"claim_id": claim_id, "status": "running"})
        except Exception:
            raise


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


# ---- מילוי ה-mirrors החסרים בדיסק, בעלייה ----------------------------------
#
# **שירות וובאפ שעולה עם דיסק בלי mirrors משכפל לבד כל ריפו שיש לו רשומה ב-``repo_metadata``**, ולפני שה-worker
# מתחיל לתפוס ג'ובים. בלי זה, אחרי מעבר לשירות חדש (או דיסק שנמחק), דפדפן הקוד לא מוצא אף ריפו, וכל ג'וב סנכרון
# נכשל על ``FAIL_MIRROR_MISSING`` עד ייבוא ידני של כל ריפו מחדש. הייבוא הידני (``initial_import``) אינו הדרך:
# הוא דורס את ``last_synced_sha``, את ``repo_url`` ואת ``default_branch`` מתוך ה-mirror, ומאנדקס הכול מחדש.
#
# המילוי רק משכפל: לא כותב למסד, לא מושך mirror שקיים (את זה עושה ה-worker, שגם מאנדקס), ולא מוחק mirror שאין לו
# רשומה (את ההסרה עושה ``unmirror_repo``, באותו שירות). החלק שמשותף לשירות ה-MCP — הקריאה מה-primary והשכפול —
# נמצא ב-``services/repo_mirror_fill.py``.
#
# **הוא עולה רק בשרת הוובאפ** (``webapp/app.py``, תחת ``_is_webapp_runtime``), כמו מתזמן הגיבויים ושולח הפושים:
# הבוט מייבא את ``webapp.app``, ואין לו את הדיסק.

#: ה-worker מחכה למילוי עד הזמן הזה, ואז מתחיל בכל מקרה (עם WARNING). ג'וב שמחכה לא מאבד כלום — הוא נשאר
#: ``pending`` במונגו עד שה-worker תופס אותו. ג'וב שרץ לפני שה-mirror שלו קיים נכשל ב-``FAIL_MIRROR_MISSING``,
#: והסנכרון המוצלח הבא משלים אותו. שכפול mirror של CodeBot (143MB) לקח 7 שניות בסביבת פיתוח (אוקטובר 2026, לא ב-Render),
#: ולכל שכפול יש תקרה משלו ב-``init_mirror``. כך שהזמן הזה הוא מעקה לשכפול תקוע, לא הערכה של משך המילוי.
MIRROR_FILL_WAIT_SECONDS = 30 * 60
#: כמו ``_STARTUP_DELAY_SECONDS`` ב-``mcp_server/repo_autosync.py``: לתת לשרת לסיים לעלות לפני ה-clone הראשון.
#: ``scripts/start_webapp.sh`` מתעד ש-Render רגיש לזיכרון בזמן העלייה, ו-``git clone`` הוא תהליך נוסף.
_MIRROR_FILL_STARTUP_DELAY_SECONDS = 10
_MIRROR_FILL_LOCK_POLL_SECONDS = 2.0
#: נעילת ``flock`` שמבטיחה שרק תהליך אחד ממלא, כשיש כמה workers של gunicorn על אותו דיסק. הקרנל משחרר אותה כשהתהליך
#: יוצא, כך שתהליך שמת לא משאיר נעילה תקועה. ``None``: הקובץ בתיקייה הזמנית, שנקבעת רק כשנועלים — ``gettempdir``
#: כותב ומוחק קובץ בדיקה בקריאה הראשונה שלו (``tempfile._get_default_tempdir``, Python 3.11), ולא בזמן ייבוא.
_MIRROR_FILL_LOCK_PATH: Optional[str] = None
_MIRROR_FILL_LOCK_NAME = "codebot-repo-mirror-fill.lock"
MIRROR_FILL_THREAD_NAME = "repo-mirror-fill"

_mirror_fill_start_lock = threading.Lock()
#: ה-``Event`` של המילוי בתהליך הזה, או ``None`` כשלא הותחל מילוי — ואז ה-worker לא מחכה (בוט, סקריפטים, טסטים).
#: נדלק בסוף המילוי, בכל דרך שבה הוא נגמר.
_mirror_fill_done: Optional[threading.Event] = None


def mirror_fill_enabled() -> bool:
    """``WEBAPP_REPO_AUTOFILL``: ``0``/``false``/``no``/``off`` מכבה, וכל ערך אחר (או היעדרו) משאיר פעיל."""
    return os.getenv("WEBAPP_REPO_AUTOFILL", "1").strip().lower() not in ("0", "false", "no", "off")


def fill_missing_mirrors(db: Any, mirror: Any) -> Dict[str, int]:
    """משכפל לדיסק כל ריפו שיש לו רשומה ב-``repo_metadata`` ואין לו mirror. לא כותב למסד.

    **הרשומה נקראת שוב, מה-primary, לפני השכפול ואחריו.** הרשימה נקראת פעם אחת בתחילת המעבר, ושכפול לוקח זמן,
    כך שריפו יכול להיות מוסר באמצע (``unmirror_repo``). הקריאה שלפני השכפול חוסכת שכפול של ריפו שכבר הוסר, ונותנת
    את ה-``repo_url`` העדכני. הקריאה שאחריו היא מה שמונע עותק יתום: ``unmirror_repo`` מוחק קודם את ה-mirror ואז את
    הרשומות, וכשהוא רץ בזמן השכפול הוא לא מוצא mirror למחוק — ואחר כך השכפול מסתיים. אין בוובאפ שלב שמוחק mirror
    שאין לו רשומה, ולכן mirror כזה נמחק כאן, דרך ``delete_mirror``, ונספר רק אחרי ש-``mirror_exists`` מראה שהוא איננו.

    כשל בקריאת הרשימה עולה לקורא. כשל בריפו אחד נספר ב-``errors``, נרשם, והמעבר ממשיך לבאים.
    """
    stats = {"checked": 0, "existed": 0, "cloned": 0, "no_url": 0, "removed": 0, "discarded": 0, "errors": 0}
    for meta in read_repo_records(db):
        name = str(meta.get("repo_name") or "").strip()
        if not name:
            continue
        stats["checked"] += 1
        try:
            if mirror.mirror_exists(name):
                stats["existed"] += 1
                continue
            current = read_repo_record(db, name)
            if current is None:
                stats["removed"] += 1
                continue
            outcome = clone_if_missing(name, str(current.get("repo_url") or "").strip(), mirror)
            if outcome.status == CLONE_EXISTS:
                stats["existed"] += 1
            elif outcome.status == CLONE_NO_URL:
                stats["no_url"] += 1
                logger.warning("repo mirror fill: %s has no repo_url in repo_metadata; not cloned", name)
            elif outcome.status != CLONE_CLONED:
                stats["errors"] += 1
                logger.warning("repo mirror fill: clone failed for %s: %s", name, outcome.message)
            elif read_repo_record(db, name) is not None:
                stats["cloned"] += 1
            else:
                _discard_clone_of_removed_repo(name, mirror, stats)
        except Exception:
            stats["errors"] += 1
            logger.warning("repo mirror fill: %s failed", name, exc_info=True)
    return stats


def _discard_clone_of_removed_repo(name: str, mirror: Any, stats: Dict[str, int]) -> None:
    res = mirror.delete_mirror(name) or {}
    # המצב, לא הדיווח: נספר כמחוק רק כשהתיקייה באמת איננה (K11).
    if res.get("success") and not mirror.mirror_exists(name):
        stats["discarded"] += 1
        logger.info("repo mirror fill: %s was removed while it was being cloned; the clone was deleted", name)
        return
    stats["errors"] += 1
    if res.get("success"):
        logger.warning(
            "repo mirror fill: %s was removed while it was being cloned; delete_mirror reported the clone deleted, "
            "but it is still on disk",
            name,
        )
        return
    logger.warning(
        "repo mirror fill: %s was removed while it was being cloned, and deleting the clone failed: %s",
        name,
        redact(res.get("message")),
    )


def _acquire_mirror_fill_lock(deadline: float) -> Tuple[bool, Any]:
    """``(להמשיך?, הקובץ שמחזיק את הנעילה)``. הקורא סוגר את הקובץ — וזה מה שמשחרר את הנעילה.

    תהליך שהנעילה תפוסה אצל תהליך אחר מחכה לו, ולא מדלג: ה-worker שלו מחכה ל-``Event`` של התהליך הזה, ו-``Event``
    שנדלק לפני שהתהליך השני סיים היה משחרר אותו מוקדם מדי. אחרי שהנעילה מתקבלת המילוי רץ גם כאן, ומוצא את הכול
    קיים. ההמתנה תחומה ב-``deadline``, ואחריו התהליך מוותר (``False``).

    בלי ``fcntl`` (לא Unix), או כשאי אפשר לפתוח את קובץ הנעילה, ממשיכים בלי נעילה ורושמים את זה: עם worker אחד אין
    לנעילה תפקיד, ועם כמה — השורה בלוג היא מה שמסביר שכפול כפול.
    """
    try:
        import fcntl
    except ImportError:
        logger.info("repo mirror fill: fcntl is not available; filling without the cross-process lock")
        return True, None
    path = _MIRROR_FILL_LOCK_PATH or os.path.join(tempfile.gettempdir(), _MIRROR_FILL_LOCK_NAME)
    try:
        fh = open(path, "a+")
    except OSError:
        logger.warning("repo mirror fill: cannot open %s; filling without the cross-process lock", path, exc_info=True)
        return True, None
    while True:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True, fh
        except BlockingIOError:
            # נעילה שתפוסה אצל אחר. נמדד ב-Python 3.11 וב-3.13 על Linux: ``BlockingIOError`` עם ``EAGAIN``.
            # כל ``OSError`` אחר אינו "תפוס", ועולה לקורא.
            if time.monotonic() >= deadline:
                fh.close()
                logger.warning(
                    "repo mirror fill: another process has been filling for %ss; this process stops waiting for it",
                    MIRROR_FILL_WAIT_SECONDS,
                )
                return False, None
            time.sleep(_MIRROR_FILL_LOCK_POLL_SECONDS)
        except BaseException:
            fh.close()
            raise


def _run_mirror_fill(done: threading.Event) -> None:
    try:
        time.sleep(_MIRROR_FILL_STARTUP_DELAY_SECONDS)
        proceed, lock_fh = _acquire_mirror_fill_lock(time.monotonic() + MIRROR_FILL_WAIT_SECONDS)
        try:
            if proceed:
                from database.db_manager import get_db

                started = time.monotonic()
                stats = fill_missing_mirrors(get_db(), get_mirror_service())
                log = logger.warning if stats["errors"] else logger.info
                log("repo mirror fill finished in %.1fs: %s", time.monotonic() - started, stats)
        finally:
            if lock_fh is not None:
                lock_fh.close()
    except Exception:
        logger.exception(
            "repo mirror fill failed; a mirror missing from this disk stays missing until the next restart, "
            "or until the repo is imported again"
        )
    finally:
        done.set()


def start_mirror_fill() -> bool:
    """מרים את חוט המילוי (פעם אחת לתהליך). ``True`` כשהוא רץ או רץ קודם, ``False`` כשהוא כבוי.

    ה-``Event`` מתפרסם **לפני** שהחוט עולה, כך ש-worker שמתחיל באותו רגע מחכה לו. כשהעלאת החוט נכשלת, ה-``Event``
    נדלק (מי שכבר מחכה לו משתחרר), הפרסום מתבטל (קריאה הבאה תנסה שוב), והחריגה עולה לקורא, שרושם אותה.
    """
    global _mirror_fill_done
    if not mirror_fill_enabled():
        logger.info("repo mirror fill disabled via WEBAPP_REPO_AUTOFILL")
        return False
    with _mirror_fill_start_lock:
        if _mirror_fill_done is not None:
            return True
        done = threading.Event()
        _mirror_fill_done = done
        try:
            threading.Thread(target=_run_mirror_fill, args=(done,), name=MIRROR_FILL_THREAD_NAME, daemon=True).start()
        except BaseException:
            done.set()
            _mirror_fill_done = None
            raise
    logger.info("repo mirror fill started (pid=%s)", os.getpid())
    return True


def _wait_for_mirror_fill() -> None:
    """ה-worker לא תופס ג'וב לפני שהמילוי בתהליך הזה הסתיים — עד ``MIRROR_FILL_WAIT_SECONDS``."""
    done = _mirror_fill_done
    if done is None or done.is_set():
        return
    logger.info("Sync worker waits for the repo mirror fill (up to %ss) before claiming jobs", MIRROR_FILL_WAIT_SECONDS)
    if done.wait(MIRROR_FILL_WAIT_SECONDS):
        logger.info("Repo mirror fill is done; the sync worker starts claiming jobs")
        return
    logger.warning(
        "Repo mirror fill is still running after %ss; the sync worker starts claiming jobs anyway, "
        "and a job for a repo whose mirror is not on disk yet fails as %s",
        MIRROR_FILL_WAIT_SECONDS,
        FAIL_MIRROR_MISSING,
    )


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

    _wait_for_mirror_fill()
    logger.info("Sync worker polling MongoDB...")

    while True:
        try:
            db = get_db()

            # Atomic: מצא job pending ותפוס אותו
            # חשוב: return_document הוא Enum ב-PyMongo, לא True/False!
            job = _claim_next_job(db)

            if not job:
                # אין jobs - ישן 5 שניות
                time.sleep(5)
                continue

            job_id = job["_id"]
            logger.info(f"Processing sync job: {job_id}")

            try:
                result = _run_sync_from_doc(job, db)
                _finish_job(db, job, result)

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


def _finish_job(db: Any, job: Dict[str, Any], result: Dict[str, Any]) -> str:
    """כותב לג'וב את הסטטוס הסופי שהתוצאה נותנת (:func:`_job_status_for`), ומחזיר אותו.

    ``result`` נשמר תמיד, גם בכשל — שם ה-``error`` לאדם ופרטי ה-fetch. ``error`` של הג'וב הוא הסיבה הקצרה
    (``FAIL_*``), כמו ש-``get_job_status`` מחזיר אותה. כשל שנזרק כחריגה עובר במסלול נפרד ב-``_sync_worker``.
    """
    job_id = job["_id"]
    status, error = _job_status_for(result)
    _update_job_with_retry(
        db,
        job_id,
        # שעה מודעת-אזור (R7). במונגו היא נשמרת כאותו ערך UTC כמו ``utcnow()`` של שאר השדות בקובץ.
        {"$set": {"status": status, "completed_at": datetime.now(timezone.utc), "result": result, "error": error}},
    )
    if status == JOB_FAILED:
        logger.warning("Sync job %s for %s failed: %s", job_id, job.get("repo_name"), error)
    elif status == JOB_SKIPPED:
        logger.info("Sync job %s for %s skipped: %s", job_id, job.get("repo_name"), (result or {}).get("reason"))
    else:
        logger.info("Job %s completed successfully", job_id)
    return status


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
    webhook_before = job_doc.get("old_sha")

    return _run_sync_logic(git_service, indexer, db, repo_name, new_sha, webhook_before)


def _run_sync_logic(
    git_service: Any,
    indexer: CodeIndexer,
    db: Any,
    repo_name: str,
    new_sha: str,
    webhook_before: Optional[str],
) -> Dict[str, Any]:
    """הסנכרון של ריפו אחד ל-``new_sha``. מחזיר תוצאה עם ``status`` מפורש (``RESULT_*``), ולא זורק על כשל צפוי.

    **הבסיס של ההבדלים הוא ``last_synced_sha`` שבמסד, ולא ``before`` שב-webhook.** ``last_synced_sha`` הוא מה
    שבאמת נכנס לאינדקס, ולכן סנכרון שמצליח משלים גם את מה שג'ובים שנכשלו לפניו פספסו. עד אוקטובר 2026 הבסיס היה
    ``before``: push שהסנכרון שלו נכשל השאיר את השינויים שלו מחוץ לאינדקס לתמיד, כי ה-push הבא התחיל מה-SHA
    שאחריו. וזה גם מה שמונע ניסיון חוזר מסוכן: ג'וב ישן שרץ אחרי חדש יותר מחשב הבדלים מהמצב שבמסד, והסנכרון הבא
    מחזיר הכול למקום. ``webhook_before`` נשאר רק לשורת לוג, כשהוא שונה מהבסיס.

    הכתיבה של ``last_synced_sha`` מותנית בכך שהוא עדיין הבסיס שהסנכרון התחיל ממנו (CAS). אם סנכרון אחר הזיז אותו
    בינתיים, התוצאה היא ``FAIL_BASE_MOVED`` — המרוץ עצמו לא נפתר כאן, רק נעשה גלוי.
    """

    # ``repo_name`` ייחודי ב-``repo_metadata``: האינדקס הייחודי נוצר בעליית שירות ה-MCP (``RepoBackend``, דרך
    # ``safe_create_index``) וב-``scripts/create_repo_indexes.py``, ולכן ``find_one`` כאן הוא הרשומה ולא נציג.
    metadata = db.repo_metadata.find_one({"repo_name": repo_name})
    if metadata is None:
        return {
            "status": RESULT_SKIPPED,
            "reason": SKIP_NOT_TRACKED,
            "message": "No repo_metadata record; the repo is not tracked here (its GitHub webhook may still be set).",
        }

    if not git_service.mirror_exists(repo_name):
        return _sync_failure(FAIL_MIRROR_MISSING, "Mirror not found on this service's disk.")

    fetch_result = git_service.fetch_updates(repo_name)
    if not fetch_result["success"]:
        return _sync_failure(FAIL_FETCH, "Fetch failed", details=fetch_result)

    base_sha = metadata.get("last_synced_sha")
    if not base_sha:
        return _sync_failure(FAIL_NO_PREVIOUS_SHA, "No last_synced_sha in repo_metadata. Run initial import first.")
    old_sha = base_sha
    if webhook_before and webhook_before != base_sha:
        # המצב שהבסיס מהמסד נועד לו: push קודם לא סונכרן (או שג'ובים רצו שלא לפי הסדר).
        logger.info(
            "Sync %s: the webhook's before (%s) is not the indexed SHA (%s); syncing from the indexed SHA",
            repo_name, str(webhook_before)[:7], str(base_sha)[:7],
        )

    # אם ה-SHA זהה, אין מה לעדכן
    if old_sha == new_sha:
        # **גם כאן מרעננים את המונה.** בלי זה, סנכרון שבו הספירה נכשלה
        # התקדם ל-SHA החדש וסומן כהושלם — והסנכרון הבא לאותו SHA יוצא
        # כאן, לפני הספירה, ומשאיר את המספר הישן לתמיד. ספירה היא קריאה
        # של המצב, ולכן המקום הנכון לתקן בו סחף הוא כל מסלול שמגיע לריפו.
        refreshed = _count_indexed_files(db, repo_name)
        if refreshed is not None:
            try:
                result = db.repo_metadata.update_one(
                    {"repo_name": repo_name}, {"$set": {"total_files": refreshed}}
                )
                # **ערך ההחזרה נבדק, לא מושלך** (K11). ``$set`` שלא תפס
                # שום מסמך אינו זורק — הוא פשוט לא עושה כלום, והריענון
                # "מצליח" בשקט בזמן שהסנכרון מדווח ``up_to_date``.
                if not getattr(result, "matched_count", 0):
                    logger.warning(
                        "total_files refresh matched no repo_metadata for %s", repo_name
                    )
            except PyMongoError:
                logger.warning("Failed to refresh total_files for %s on up_to_date", repo_name)
        # **בכוונה בלי ``upsert=True``,** בשונה משני מסלולי הכתיבה האחרים.
        # הם כותבים את כל שדות המטא-דאטה ולכן יצירה שם היא מסמך שלם; כאן
        # נכתב שדה יחיד, ו-upsert היה יוצר מסמך עם ``repo_name`` ו-
        # ``total_files`` בלבד. ``/repo/api/repos`` מחזיר את **כל** מסמכי
        # ``repo_metadata`` בלי פילטר, כך שמסמך כזה היה מופיע כריפו רפאים
        # ברשימת הבחירה — בלי כתובת ובלי ענף.
        return {"status": RESULT_UP_TO_DATE, "message": "No changes"}

    # קבלת רשימת שינויים
    changes = git_service.get_changed_files(repo_name, old_sha, new_sha)

    if changes is None:
        return _sync_failure(FAIL_CHANGES_UNAVAILABLE, "Failed to get changed files")

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

    # **מונה הקבצים נספר מחדש בכל סנכרון, ולא רק בייבוא הראשוני.**
    #
    # עד כאן ``total_files`` נכתב רק ב-``initial_import``, ולכן המספר
    # שהוצג בדפדפן הריפו נשאר קפוא על מה שהיה ביום הייבוא — גם אחרי
    # עשרות מיזוגים שהוסיפו ומחקו קבצים.
    #
    # הספירה היא של ``repo_files``, שהוא בדיוק מה ש-``total_files`` מייצג
    # (בייבוא: ``len(code_files)``, כלומר הקבצים שנבחרו לאינדוקס). הסנכרון
    # מסיר משם קבצים שנמחקו ושינויי שם, ולכן הספירה משקפת את המצב האמיתי.
    #
    # **למה ספירה ולא דלתא של added/removed:** דלתא מצטברת על ערך קודם,
    # וכל כשל חלקי אחד — קובץ שדילגנו עליו, סנכרון שנקטע — נשאר בתוכה
    # לתמיד. ספירה קוראת את המצב, ולכן היא מתקנת סחף שכבר נוצר במקום
    # להנציח אותו.
    total_files = _count_indexed_files(db, repo_name)

    metadata_updates = {
        "last_synced_sha": new_sha,
        "last_sync_time": datetime.utcnow(),
        "sync_status": "completed",
        "last_sync_stats": stats,
    }
    if total_files is not None:
        metadata_updates["total_files"] = total_files

    # עדכון metadata — רק אם ``last_synced_sha`` עדיין הבסיס שהסנכרון התחיל ממנו (CAS), ובלי upsert: הרשומה קיימת
    # (ממנה נקרא הבסיס), ו-upsert עם ``last_synced_sha`` בפילטר היה יוצר רשומה שנייה לאותו ריפו.
    update = db.repo_metadata.update_one(
        {"repo_name": repo_name, "last_synced_sha": old_sha},
        {"$set": metadata_updates},
    )
    # ``matched_count`` זורק על כתיבה שלא אושרה (w=0) — ולכן ``acknowledged`` נבדק ראשון (pymongo 4.15.3, results.py),
    # כמו ב-``webapp/drive_auth.py``. ``update_one`` שלא תפס מסמך אינו זורק, ולכן התוצאה נבדקת (K11).
    if not (getattr(update, "acknowledged", False) and getattr(update, "matched_count", 0) == 1):
        logger.warning(
            "Sync %s: last_synced_sha moved from %s while syncing to %s; not recording this sync",
            repo_name, old_sha[:7], new_sha[:7],
        )
        return _sync_failure(
            FAIL_BASE_MOVED,
            "last_synced_sha changed during the sync (another sync ran at the same time).",
            old_sha=old_sha[:7], new_sha=new_sha[:7], stats=stats,
        )

    logger.info(f"Sync completed: {stats}")

    return {"status": RESULT_SYNCED, "old_sha": old_sha[:7], "new_sha": new_sha[:7], "stats": stats}


def unmirror_repo(repo_name: str, db: Any) -> Dict[str, Any]:
    """
    הסרה מלאה של ריפו מה-mirror: גם מה-DB וגם מהדיסק.

    סדר הפעולות חשוב כדי להימנע מחוסר עקביות:
    1. בדיקה שאין sync job ב-running (אחרת ה-worker יחזור לכתוב אינדקס).
    2. מחיקת ה-bare mirror מהדיסק — הפעולה הכי שברירית, חייבת להצליח לפני
       שנוגעים ב-DB.
    3. ניקוי DB: `repo_files`, `repo_metadata`, `sync_jobs` ממתינים,
       ו-`selected_repo` ממשתמשים שבחרו דווקא בריפו הזה.

    Args:
        repo_name: שם הריפו
        db: חיבור ל-MongoDB

    Returns:
        dict עם success, וסטטיסטיקות על מה נמחק (לטובת UI/לוגים)
    """
    git_service = get_mirror_service()

    repo_name = str(repo_name or "").strip()
    if not git_service._validate_repo_name(repo_name):
        return {"success": False, "error": "invalid_repo_name", "message": "Invalid repo name"}

    stats: Dict[str, Any] = {
        "files_removed": 0,
        "metadata_removed": 0,
        "pending_jobs_removed": 0,
        "users_unset": 0,
        "mirror_existed": False,
        "mirror_deleted": False,
        "blocked_due_to_running_job": False,
    }

    # 1) חסימה אם קיים sync job פעיל בפועל - בלי תופעות לוואי.
    #    אם נחזיר sync_in_progress, שום דבר לא נמחק.
    try:
        running_job = db.sync_jobs.find_one({"repo_name": repo_name, "status": "running"})
    except Exception:
        logger.exception(f"Failed to query sync_jobs for {repo_name}")
        return {
            "success": False,
            "error": "database_error",
            "message": "Failed to query sync state",
            "stats": stats,
        }
    if running_job:
        stats["blocked_due_to_running_job"] = True
        logger.warning(
            f"Refusing to unmirror {repo_name}: sync job is currently running"
        )
        return {
            "success": False,
            "error": "sync_in_progress",
            "message": "Sync job is currently running for this repo; try again shortly",
            "stats": stats,
        }

    # 2) ניקוי jobs ממתינים אחרי שאישרנו שאין running. מצמצם את חלון ה-race:
    #    worker שיתפוס job אחרי השלב הזה לא ימצא את הריפו ב-pending.
    try:
        result = db.sync_jobs.delete_many({"repo_name": repo_name, "status": "pending"})
        stats["pending_jobs_removed"] = int(getattr(result, "deleted_count", 0) or 0)
    except Exception:
        logger.warning(f"Failed to clean pending sync_jobs for {repo_name}", exc_info=True)

    # 3) מחיקת ה-mirror מהדיסק *לפני* שנוגעים ביתר ה-DB. אם הדיסק נכשל - DB
    #    נשאר ברובו שלם (למעט pending שכבר נוקו - מקובל כי בלאו הכי לא רץ סנכרון).
    #    אם worker תפס job בחלון בין שלב 1 ל-3, ה-`mirror_exists` שלו יחזיר
    #    False ב-`_run_sync_logic` והוא יחזור עם error בלי לכתוב לאינדקס.
    delete_result = git_service.delete_mirror(repo_name)
    stats["mirror_existed"] = bool(delete_result.get("existed"))
    stats["mirror_deleted"] = bool(delete_result.get("success") and delete_result.get("existed"))

    if not delete_result.get("success"):
        logger.error(
            f"Failed to delete mirror directory for {repo_name}: "
            f"{delete_result.get('message')}"
        )
        return {
            "success": False,
            "error": "mirror_delete_failed",
            "message": "Failed to delete mirror directory",
            "stats": stats,
        }

    # 4) מחיקת אינדקס הקבצים
    try:
        result = db.repo_files.delete_many({"repo_name": repo_name})
        stats["files_removed"] = int(getattr(result, "deleted_count", 0) or 0)
    except Exception:
        logger.exception(f"Failed to delete repo_files for {repo_name}")
        return {
            "success": False,
            "error": "database_error",
            "message": "Failed to delete repo files index",
            "stats": stats,
        }

    # 5) מחיקת מטא-דאטה של הריפו
    try:
        result = db.repo_metadata.delete_many({"repo_name": repo_name})
        stats["metadata_removed"] = int(getattr(result, "deleted_count", 0) or 0)
    except Exception:
        logger.exception(f"Failed to delete repo_metadata for {repo_name}")
        return {
            "success": False,
            "error": "database_error",
            "message": "Failed to delete repo metadata",
            "stats": stats,
        }

    # 6) ניקוי בחירת ריפו מהמשתמשים
    try:
        result = db.users.update_many(
            {"selected_repo": repo_name},
            {"$unset": {"selected_repo": ""}},
        )
        stats["users_unset"] = int(getattr(result, "modified_count", 0) or 0)
    except Exception:
        logger.warning(f"Failed to unset selected_repo for {repo_name}", exc_info=True)

    logger.info(f"Unmirrored {repo_name}: {stats}")
    return {"success": True, "repo_name": repo_name, "stats": stats}


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

    # 2. זיהוי ה-Default Branch האמיתי — מה ש-HEAD של המראה מצביע עליו.
    # **בלי ניחוש:** עד #3479 כל ניסיון כאן נדחה ב-``_run_git_command`` ("Unsupported
    # git subcommand") והזיהוי נפל תמיד ל-``main``. כשאין ענף מאומת — כשל עם שם.
    detected = git_service.detect_default_branch(repo_name)
    default_branch = detected.get("branch")
    if not default_branch:
        logger.error(
            "Could not detect default branch for %s (%s)", repo_name, detected.get("reason")
        )
        return {
            "error": "default_branch_undetected",
            "details": detected.get("reason"),
            "repo_name": repo_name,
        }

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

    # 4.5 יישוב האינדקס מול הריפו.
    #
    # ``index_file`` הוא upsert לפי ``(repo_name, path)``, ולכן ייבוא חוזר
    # על מראה קיימת מעדכן ומוסיף — אבל **לעולם לא מסיר** נתיבים שכבר אינם
    # בריפו. הרפאים האלה אינם רק מספר: הם מופיעים בעץ הקבצים ובחיפוש.
    # הסנכרון האינקרמנטלי כבר עושה בדיוק את זה (``remove_files`` על
    # ``changes["removed"]``); כאן זה חסר.
    #
    # המחיקה היא **הפרש מפורש** ולא גורף: הנתיבים שקיימים באינדקס פחות
    # אלה שנבחרו עכשיו לאינדוקס, ורק דרך ``remove_files`` הקיים.
    #
    # **התנאי הוא ``is not None`` ולא "לא ריק".** רשימה ריקה אינה כשל אלא
    # ריפו ריק — כשל בליסטינג מוחזר כ-``None`` ומחזיר שגיאה עוד למעלה,
    # לפני שמגיעים לכאן. עם הבדיקה הקודמת, ריפו שכל קבציו נמחקו היה נשאר
    # עם אינדקס מלא רפאים: הם ממשיכים להופיע בעץ ובחיפוש, ומאז שהמונה
    # נספר מהאינדקס — גם מנפחים אותו.
    if all_files is not None:
        try:
            existing_paths = set(db.repo_files.distinct("path", {"repo_name": repo_name}))
        except PyMongoError:
            existing_paths = None
            logger.warning("Could not list indexed paths for %s; skipping reconcile", repo_name)
        if existing_paths is not None:
            stale_paths = sorted(existing_paths - set(code_files))
            if stale_paths:
                removed = indexer.remove_files(repo_name, stale_paths)
                logger.info(
                    "Reconcile: removed %s stale indexed paths for %s", removed, repo_name
                )

    # 5. שמירת metadata (כולל default_branch לשימוש בחיפוש ובסנכרון)
    #
    # ספירה אמיתית של מה שנכנס לאינדקס — אחרי היישוב, ולכן בלי רפאים.
    # נפילה חוזרת ל-``indexed_count`` שנספר בלולאה, שקרוב יותר לאמת
    # מ-``len(code_files)`` שכולל גם קבצים שנכשלו.
    counted = _count_indexed_files(db, repo_name)
    imported_count = counted if counted is not None else indexed_count

    db.repo_metadata.update_one(
        {"repo_name": repo_name},
        {
            "$set": {
                "repo_url": repo_url,
                "default_branch": default_branch,  # חשוב! לשימוש ב-git grep וב-sync
                "last_synced_sha": current_sha,
                "last_sync_time": datetime.utcnow(),
                # אותה הגדרה בדיוק כמו במסלול הסנכרון — הקבצים שבאמת
                # נכנסו לאינדקס. ``len(code_files)`` היה סופר גם כאלה
                # שהאינדוקס שלהם נכשל, ולכן ריפו עם שגיאות ייבוא היה קופץ
                # למספר אחר בסנכרון הראשון בלי ששום קובץ השתנה.
                "total_files": imported_count,
                "sync_status": "completed",
                "initial_import": True,
            }
        },
        upsert=True,
    )

    logger.info(f"Initial import completed: {indexed_count} files indexed")

    return {
        "status": "completed",
        # עקביות מול מה שנשמר ב-MongoDB: אותו ערך בדיוק
        "total_files": imported_count,
        # שדה נוסף למספר כל הקבצים בריפו (כולל לא-מאונדקסים)
        "total_git_files": len(all_files),
        "code_files": len(code_files),
        "indexed": indexed_count,
        "errors": error_count,
        "sha": current_sha[:7],
    }

