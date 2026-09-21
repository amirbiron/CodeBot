"""פיוס הרצות יתומות באוסף ``job_runs``.

**הבעיה.** ‏``JobTracker`` מסמן הרצה כ-``running`` ברגע שהיא מתחילה, ומעדכן
את הסטטוס הסופי כשהיא נגמרת. אם התהליך מת באמצע — דיפלוי, ‏SIGKILL, קריסה —
אף אחד לא כותב את הסוף, והרשומה נשארת ``running`` עד שאינדקס ה-TTL מוחק
אותה. בדשבורד היא נראית כהרצה חיה, ו-``/api/jobs/active`` מחזיר אותה.

**מה מאפשר להכריע.** ג'ובים רצים רק תחת מנעול ה-singleton של מונגו, ויש לו
מחזיק אחד בכל רגע. לכן הרצה שהתחילה **לפני** שהתהליך הנוכחי קיבל את המנעול
שייכת למחזיק קודם. המבחן הוא **זמן ולא זהות**: ‏``owner_id`` נגזר מ-
``RENDER_INSTANCE_ID`` ו-PID, ו-PIDים חוזרים בקונטיינרים, ולכן אסור לבנות
עליו מבחן.

**מה המודול הזה לא מבטיח.** שהתהליך הקודם כבר מת. ההשהיה שלפני הקריאה היא
מה שהופך את ההנחה לסבירה, והנימוק המלא — כולל המקרה שאינו מכוסה והנזק בו —
יושב בהערה מעל ``_RECONCILE_DELAY_SECS_DEFAULT``, במקום שבו המספר נקבע.

**הכתיבה מוגנת.** לכל מסמך יוצא עדכון מותנה (``status: "running"``), ומספר
המסמכים שנתפסו נבדק ונרשם. הרצה שהספיקה להסתיים בין השליפה לעדכון אינה
נדרסת, והדחייה אינה נבלעת.
"""

from __future__ import annotations

import logging
import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.job_registry import env_toggle_enabled
from services.job_tracker import JOB_RUN_LOGS_KEPT, JobStatus

logger = logging.getLogger(__name__)

#: הערך שנכתב ל-``failure_reason``. מי שקורא אותו ומבדיל: ‏``handle_jobs_command``
#: ב-``chatops/jobs_commands.py`` (👻 במקום ❌, גם ב-``failed`` וגם בהיסטוריית
#: ג'וב, דרך ``JobRun.failure_reason``), ו-``_job_run_doc_to_dict`` ב-``webapp/app.py``
#: שמחזיר אותו ב-API. תבנית הדשבורד עדיין אינה מציגה אותו. בלי השדה "הכשלונות
#: האחרונים" היו מערבבים ג'וב שנפל בקוד שלו עם הרצה שאיש לא סגר.
ORPHANED_FAILURE_REASON = "orphaned"

#: מה שנכתב ל-``error_message`` ומוצג למשתמש בדשבורד. שתי הטענות כאן
#: נבדקות מהקוד: התהליך שהתחיל את ההרצה אינו מחזיק המנעול הנוכחי, וההרצה
#: לא כתבה סטטוס סופי. אין כאן טענה שהתהליך מת — ראה את ההערה על ההשהיה.
ORPHANED_ERROR_MESSAGE = "התהליך שהתחיל את ההרצה כבר אינו מריץ ג'ובים, וההרצה לא דיווחה על סיום"

#: כמה מסמכים נשלפים בבת אחת. כל מסמך שמטופל יוצא מקבוצת הסינון (הסטטוס
#: שלו מפסיק להיות ``running``), ולכן הלולאה מתכנסת בלי סמן.
_BATCH_SIZE = 200

#: תקרה קשיחה על מספר ההרצות שיטופלו בקריאה אחת. היא קיימת כדי שתקלה
#: שמחזירה את אותם מסמכים שוב ושוב לא תרוץ לנצח; כשהיא נתפסת זה נרשם
#: במפורש ולא נבלע.
_MAX_RUNS = 2000

#: השדות היחידים שנקראים מהמסמך. בלי היטלה הייתה נגררת גם ``logs`` וגם
#: ``result`` על כל הרצה שנשלפת.
_PROJECTION = {"run_id": 1, "job_id": 1, "started_at": 1}

#: כמה מזהי ג'וב נכנסים לאירוע הסיכום. השם אומר "מדגם" כדי שקורא לא יסיק
#: מאורך הרשימה כמה הרצות טופלו — המספר המלא יושב ב-``count``.
_EVENT_JOB_ID_SAMPLE = 20

#: כמה שניות ממתינים אחרי עליית התהליך לפני שמפייסים.
#:
#: **מה ההשהיה מבטיחה — ורק זה.** את מסלול הדיפלוי. לפי התיעוד של Render
#: (https://render.com/docs/deploys): *"After 60 seconds, Render sends a
#: ``SIGTERM`` signal to your app's process on the original instance"*,
#: ואחריו *"If your app's process doesn't exit within its specified shutdown
#: delay (default 30 seconds), Render sends a ``SIGKILL``"*. ‏``render.yaml``
#: כאן אינו קובע ערך מותאם, ולכן ברירת המחדל חלה. כלומר מרגע שהמחזיק החדש
#: יכול לקבל את המנעול ועד שהישן מת בוודאות עוברות 90 שניות לכל היותר,
#: ו-SIGKILL הוא הערובה: אחריו שום שורה מהתהליך הישן אינה רצה. ברירת המחדל
#: כאן היא כפליים מזה. מי שמעלה את ה-shutdown delay ב-Render (עד 300 לפי
#: אותו עמוד) חייב להעלות גם את הערך הזה.
#:
#: **מה היא אינה מבטיחה.** את המסלול שבו ה-heartbeat של המחזיק הקודם נכשל
#: בלי שיש דיפלוי. שם אין SIGKILL בכלל: התהליך הישן יוצא רק כשבדיקת הבעלות
#: שלו מספיקה לרוץ, ואם הוא תקוע באותה קריאת מונגו שהכשילה את ה-heartbeat —
#: אין חסם זמן על ההמתנה. קריאה אחת חוסמת עד ``MONGODB_SERVER_SELECTION_TIMEOUT_MS``
#: ועוד ``MONGODB_SOCKET_TIMEOUT_MS``, ו-``MONGODB_RETRY_WRITES`` מאפשר
#: לשלם את זה פעם נוספת. שני הכשלים האלה הם באגים של הנעילה עצמה, והם
#: מתועדים באישיו #3452 — אין כאן ניסיון לתקן אותם.
#:
#: **הנזק במקרה שאינו מכוסה.** רשומת הרצה אחת שמסומנת ``failed`` עם
#: ``failure_reason: "orphaned"`` אף שההרצה עדיין חיה. זו רשומה שקרית, ולא
#: עצירה של ההרצה — הפיוס כותב לרשומה בלבד ואינו נוגע בתהליך. והיא מתקנת
#: את עצמה אם ההרצה מגיעה לסופה: ``_persist_run`` לעולם אינו חוסם כתיבה
#: **סופית**, ולכן התוצאה האמיתית דורסת את הסימון. היא נשארת שגויה רק אם
#: התהליך הישן מת אחרי הפיוס ולפני שכתב את התוצאה.
_RECONCILE_DELAY_SECS_DEFAULT = 180

#: תקרת זמן על הפיוס **כולו** — לא על קריאה בודדת. הלקוח שהפיוס רץ עליו
#: נבנה ב-``main.py`` (``_get_scheduler_motor_db``) בלי ארגומנטים, ולכן
#: ``socketTimeoutMS`` הוא ברירת המחדל של הדרייבר — ``None``, כלומר אין תקרה
#: (נקרא מ-``MongoClient(...).options`` של pymongo 4.18.1 המותקן; הריפו מצמיד
#: 4.15.3). בלי דדליין משלו, קריאה שנתקעה על הסוקט הייתה תוקעת ג'וב חד-פעמי
#: לנצח, בשקט. הגודל נגזר מהסריקה הגדולה ביותר: ``_MAX_RUNS`` עדכונים ועוד
#: ``_MAX_RUNS // _BATCH_SIZE`` שליפות, בתקציב של עשרות אלפיות שנייה לפעולה
#: — הנחה, לא מדידה. התקרה נועדה להפוך תקיעה לתוצאה רשומה; תקיעה נמשכת
#: דקות עד לעולם, ולכן המספר המדויק אינו קריטי כל עוד הוא גדול מריצה תקינה.
RECONCILE_TIMEOUT_SECS = 120

#: מינימום. השהיה קצרה מזה מכניסה את הפיוס לתוך חלון הסגירה של Render,
#: כלומר בדיוק לזמן שבו שני התהליכים חיים יחד.
_RECONCILE_DELAY_SECS_MIN = 90

#: האם הפיוס פעיל כשהמשתנה כלל אינו מוגדר. נקרא גם ב-``register_jobs``
#: בתור ``env_toggle_default``, כדי שהדשבורד והתזמון יגזרו מאותו ערך.
RECONCILE_ENABLED_DEFAULT = True


def reconcile_enabled() -> bool:
    """האם הפיוס פעיל.

    הכלל עצמו חי ב-``job_registry.env_toggle_enabled``, ולא בעותק כאן:
    ‏``JobRegistry.is_enabled`` קובע מה הדשבורד מציג, ושתי תשובות שונות
    לאותה שאלה היו מראות "מושבת" בזמן שהפיוס רץ.

    נקרא בזמן התזמון ולא בזמן הייבוא, כדי שערך שנקבע אחרי עליית המודול
    (ובבדיקות) ייקרא בפועל — אותה צורה שבה ``job_runs_ttl_seconds`` עובדת.
    """
    return env_toggle_enabled(
        os.getenv("JOBS_ORPHAN_RECONCILE_ENABLED"), RECONCILE_ENABLED_DEFAULT
    )


def reconcile_delay_seconds() -> int:
    """ההשהיה בפועל, לפי ``JOBS_ORPHAN_RECONCILE_DELAY_SECS``.

    ראה את ההערה מעל ``_RECONCILE_DELAY_SECS_DEFAULT`` — שם יושב הנימוק
    המלא, כולל מה ההשהיה אינה מבטיחה.
    """
    try:
        value = int(os.getenv("JOBS_ORPHAN_RECONCILE_DELAY_SECS", "") or _RECONCILE_DELAY_SECS_DEFAULT)
    except (TypeError, ValueError):
        value = _RECONCILE_DELAY_SECS_DEFAULT
    return max(_RECONCILE_DELAY_SECS_MIN, value)


def _emit_event(event: str, **fields: Any) -> None:
    """שליחת אירוע, בלי להפיל את הפיוס אם שכבת האירועים לא זמינה."""
    try:
        from observability import emit_event

        emit_event(event, **fields)
    except Exception:
        # ‏fire-and-forget מוצהר: אירוע שלא נשלח אינו סיבה להשאיר הרצות
        # יתומות פתוחות. נרשם כדי שלא ייעלם בשקט.
        logger.warning("job_runs_reconciled event emit failed", exc_info=True)


def _clean_text(value: Any) -> str:
    """ערך שהגיע ממסמך מונגו — לא בהכרח מחרוזת."""
    if not isinstance(value, str):
        return ""
    return value.strip()


async def reconcile_orphan_runs(
    collection: Any,
    *,
    lock_acquired_at: datetime,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """סוגר הרצות ``running`` שהתחילו לפני ``lock_acquired_at``.

    Args:
        collection: אוסף ``job_runs`` בממשק אסינכרוני (motor).
        lock_acquired_at: מתי **התהליך הזה** קיבל את מנעול ה-singleton.
            ערך מודע-אזור-זמן. ‏``None`` אינו מטופל כאן אלא אצל הקורא: בלי
            רגע רכישה ידוע אין מבחן, ופיוס בלי מבחן היה מסמן הרצות חיות.
        now: שעת הכתיבה, להזרקה בבדיקות.

    Returns:
        סיכום: ``scanned`` (כמה מסמכים נשלפו), ‏``reconciled`` (כמה עודכנו
        בפועל), ‏``skipped`` (כמה נדחו כי הסטטוס כבר השתנה), ‏``truncated``
        (האם התקרה נתפסה), ו-``job_ids``.

    Raises:
        TypeError: אם ``lock_acquired_at`` — או ``now``, כשהועבר — אינו ``datetime`` מודע אזור זמן.
            השוואה מול ערך נאיבי הייתה זורקת בתוך מונגו או, גרוע מכך,
            מסננת לפי רגע אחר.
    """
    if not isinstance(lock_acquired_at, datetime) or lock_acquired_at.tzinfo is None:
        raise TypeError("lock_acquired_at must be a timezone-aware datetime")

    # אותו כלל לשני ערכי הזמן: נאיבי נדחה, לא מוחלף בשקט בשעת השרת.
    if now is None:
        now = datetime.now(timezone.utc)
    elif not isinstance(now, datetime) or now.tzinfo is None:
        raise TypeError("now must be a timezone-aware datetime")
    stamp = now

    scanned = 0
    reconciled = 0
    skipped = 0
    truncated = False
    job_ids: List[str] = []
    # מסמכים שלא יכולנו לפעול עליהם **בכלל** — אין להם ``run_id``, ולכן
    # אין עדכון מוגן שאפשר לשלוח. הם היו חוזרים בכל שליפה, ולכן מוחרגים.
    # ‏**הרצות שנדחו ב-CAS אינן כאן:** דחייה פירושה שהסטטוס כבר אינו
    # ``running``, כלומר הן יצאו מקבוצת הסינון בעצמן.
    unresolved_ids: List[Any] = []

    while True:
        if scanned >= _MAX_RUNS:
            truncated = True
            break

        # ‏``status`` בשוויון ו-``started_at`` בטווח — בדיוק הצורה
        # ש-``idx_job_runs_status_time`` משרת, ולפי ESR.
        query: Dict[str, Any] = {
            "status": JobStatus.RUNNING.value,
            "started_at": {"$lt": lock_acquired_at},
        }
        if unresolved_ids:
            query["_id"] = {"$nin": unresolved_ids}

        cursor = collection.find(query, _PROJECTION).limit(_BATCH_SIZE)

        docs = await cursor.to_list(length=_BATCH_SIZE)
        if not docs:
            break

        for doc in docs:
            if not isinstance(doc, dict):
                continue
            scanned += 1
            run_id = _clean_text(doc.get("run_id"))
            job_id = _clean_text(doc.get("job_id"))
            if not run_id:
                # בלי מזהה הרצה אין עדכון מוגן. נרשם כדי שלא ייעלם.
                logger.warning("job run without run_id skipped during orphan reconcile")
                doc_id = doc.get("_id")
                if doc_id is not None:
                    unresolved_ids.append(doc_id)
                continue

            result = await collection.update_one(
                # ‏CAS: אם ההרצה הספיקה להסתיים בין השליפה לכאן, התוצאה
                # האמיתית שלה נשארת. אין ``upsert`` — אין מה ליצור.
                {"run_id": run_id, "status": JobStatus.RUNNING.value},
                {
                    "$set": {
                        # ארבעת השדות זזים יחד. סטטוס בלי ``ended_at``
                        # היה שובר את חישוב משך ההרצה בדשבורד, וסטטוס
                        # בלי ``failure_reason`` היה מערבב את ההרצה הזו
                        # עם ג'וב שנפל באמת.
                        "status": JobStatus.FAILED.value,
                        "ended_at": stamp,
                        "error_message": ORPHANED_ERROR_MESSAGE,
                        "failure_reason": ORPHANED_FAILURE_REASON,
                    },
                    "$push": {
                        "logs": {
                            "$each": [
                                {
                                    "timestamp": stamp,
                                    "level": "error",
                                    "message": ORPHANED_ERROR_MESSAGE,
                                    "details": {"failure_reason": ORPHANED_FAILURE_REASON},
                                }
                            ],
                            "$slice": -JOB_RUN_LOGS_KEPT,
                        }
                    },
                },
                upsert=False,
            )

            matched = int(getattr(result, "matched_count", 0) or 0)
            if matched:
                reconciled += 1
                if job_id:
                    job_ids.append(job_id)
            else:
                # לא ממצא ולא כשל: ההרצה נסגרה בעצמה בין השליפה לעדכון.
                # נרשם כי עדכון שלא הוחל שלא נרשם הוא בדיוק מה שמסתיר
                # תקלה אמיתית בפעם הבאה.
                skipped += 1
                logger.info(
                    "orphan reconcile skipped run; status changed before update",
                    extra={"event": "job_run_reconcile_skipped", "run_id": run_id},
                )

    if reconciled or truncated:
        unique_job_ids = sorted(set(job_ids))
        _emit_event(
            "job_runs_reconciled",
            severity="warn",
            count=reconciled,
            skipped=skipped,
            truncated=truncated,
            job_ids_sample=unique_job_ids[:_EVENT_JOB_ID_SAMPLE],
        )
        logger.warning(
            "closed orphan job runs from a previous lock holder",
            extra={
                "event": "job_runs_reconciled",
                "count": reconciled,
                "skipped": skipped,
                "truncated": truncated,
            },
        )

    return {
        "scanned": scanned,
        "reconciled": reconciled,
        "skipped": skipped,
        "truncated": truncated,
        "job_ids": sorted(set(job_ids)),
    }


#: כל התוצאות האפשריות של ה-callback. ערוץ אחד: מחרוזת, לעולם לא חריגה.
RECONCILE_OUTCOMES = ("skipped_no_lock", "skipped_no_db", "done", "timed_out", "failed")


async def reconcile_job_callback(get_collection, *, lock_acquired_at: Optional[datetime]) -> str:
    """גוף ה-callback של הג'וב ``jobs_orphan_reconcile``, בלי ה-JobQueue.

    ‏``main.py`` עוטף את זה בסגירה דקה שמספקת את אוסף ``job_runs`` ואת
    ``_LOCK_ACQUIRED_AT``; הלוגיקה חיה כאן כדי שאפשר יהיה לבדוק אותה.

    **ערוץ אחד לתוצאה: מחרוזת מתוך ``RECONCILE_OUTCOMES``, ולעולם לא חריגה.**
    זהו גבול של callback — חריגה כאן הייתה מפילה את התור — וכל תוצאה
    נרשמת בלוג עם שם אירוע משלה, כדי ש"לא רץ", "נחתך" ו"רץ ולא מצא כלום"
    ייראו שונה זה מזה. השמות נמצאים ב-``docs/observability/events_catalog.rst``.

    Args:
        get_collection: קורוטינה שמחזירה את אוסף ``job_runs`` (motor) או ``None``.
        lock_acquired_at: ‏``_LOCK_ACQUIRED_AT`` של התהליך, או ``None`` כשאין מנעול.
    """
    if lock_acquired_at is None:
        # הרצה בלי מנעול (LOCK_FAIL_OPEN, או כשל בהעלאת ה-heartbeat): ייתכן
        # שתהליך אחר מריץ ג'ובים ממש עכשיו, וכל ``running`` יכול להיות שלו.
        # בלי מבחן אין פיוס.
        logger.warning(
            "orphan reconcile skipped: this process holds no lock acquisition time",
            extra={"event": "jobs_orphan_reconcile_skipped", "reason": "no_lock"},
        )
        return "skipped_no_lock"

    try:
        collection = await get_collection()
    except Exception:
        logger.exception("orphan reconcile failed", extra={"event": "jobs_orphan_reconcile_failed"})
        return "failed"
    if collection is None or not hasattr(collection, "find"):
        logger.warning(
            "orphan reconcile skipped: job_runs collection is unavailable",
            extra={"event": "jobs_orphan_reconcile_skipped", "reason": "no_db"},
        )
        return "skipped_no_db"

    try:
        # ‏``wait_for`` מבטל את המשימה הפנימית וזורק ``TimeoutError`` כשהזמן
        # נגמר (מקור: ``asyncio.tasks.wait_for``, Python 3.11). הדדליין חל על
        # הלולאה כולה — כל השליפות וכל העדכונים — ולא על קריאה אחת.
        summary = await asyncio.wait_for(
            reconcile_orphan_runs(collection, lock_acquired_at=lock_acquired_at),
            timeout=RECONCILE_TIMEOUT_SECS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "orphan reconcile timed out; unclosed runs wait for the next startup",
            extra={"event": "jobs_orphan_reconcile_timed_out", "timeout_seconds": RECONCILE_TIMEOUT_SECS},
        )
        return "timed_out"
    except Exception:
        # פיוס שנכשל בשקט היה משאיר את הזומבים בלי שאיש ידע.
        logger.exception("orphan reconcile failed", extra={"event": "jobs_orphan_reconcile_failed"})
        return "failed"

    if not summary["reconciled"]:
        # "רץ ולא מצא כלום" חייב להיראות שונה מ"לא רץ". אירוע (``_emit_event``)
        # לא נשלח כאן — זה המצב הרגיל בכל עלייה — רק שורת לוג עם אותו שם.
        logger.info(
            "orphan reconcile found nothing to close",
            extra={"event": "job_runs_reconciled", "count": 0, "scanned": summary["scanned"]},
        )
    return "done"
