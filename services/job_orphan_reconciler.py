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
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.job_tracker import JOB_RUN_LOGS_KEPT, JobStatus

logger = logging.getLogger(__name__)

#: הערך שנכתב ל-``failure_reason``. הצרכן שלו הוא ``_job_run_doc_to_dict``
#: בוובאפ, שמעביר אותו לדשבורד — שם מבדילים בין ג'וב שנפל לבין הרצה שאיש
#: לא סגר. ‏``/jobs failed`` ב-ChatOps מציג את שתי הקבוצות יחד, ולכן בלי
#: השדה הזה "הכשלונות האחרונים" היו מערבבים שתי אוכלוסיות.
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
#: מתועדים באישיו נפרד — אין כאן ניסיון לתקן אותם.
#:
#: **הנזק במקרה שאינו מכוסה.** רשומת הרצה אחת שמסומנת ``failed`` עם
#: ``failure_reason: "orphaned"`` אף שההרצה עדיין חיה. זו רשומה שקרית, ולא
#: עצירה של ההרצה — הפיוס כותב לרשומה בלבד ואינו נוגע בתהליך. והיא מתקנת
#: את עצמה אם ההרצה מגיעה לסופה: ``_persist_run`` לעולם אינו חוסם כתיבה
#: **סופית**, ולכן התוצאה האמיתית דורסת את הסימון. היא נשארת שגויה רק אם
#: התהליך הישן מת אחרי הפיוס ולפני שכתב את התוצאה.
_RECONCILE_DELAY_SECS_DEFAULT = 180

#: מינימום. השהיה קצרה מזה מכניסה את הפיוס לתוך חלון הסגירה של Render,
#: כלומר בדיוק לזמן שבו שני התהליכים חיים יחד.
_RECONCILE_DELAY_SECS_MIN = 90


def reconcile_enabled() -> bool:
    """האם הפיוס פעיל. ברירת המחדל פעילה.

    נקרא בזמן התזמון ולא בזמן הייבוא, כדי שערך שנקבע אחרי עליית המודול
    (ובבדיקות) ייקרא בפועל — אותה צורה שבה ``job_runs_ttl_seconds`` עובדת.
    """
    raw = str(os.getenv("JOBS_ORPHAN_RECONCILE_ENABLED", "") or "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


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
        TypeError: אם ``lock_acquired_at`` אינו ``datetime`` מודע אזור זמן.
            השוואה מול ערך נאיבי הייתה זורקת בתוך מונגו או, גרוע מכך,
            מסננת לפי רגע אחר.
    """
    if not isinstance(lock_acquired_at, datetime) or lock_acquired_at.tzinfo is None:
        raise TypeError("lock_acquired_at must be a timezone-aware datetime")

    stamp = now if isinstance(now, datetime) and now.tzinfo is not None else datetime.now(timezone.utc)

    scanned = 0
    reconciled = 0
    skipped = 0
    truncated = False
    job_ids: List[str] = []

    while True:
        if scanned >= _MAX_RUNS:
            truncated = True
            break

        cursor = collection.find(
            # ‏``status`` בשוויון ו-``started_at`` בטווח — בדיוק הצורה
            # ש-``idx_job_runs_status_time`` משרת, ולפי ESR.
            {"status": JobStatus.RUNNING.value, "started_at": {"$lt": lock_acquired_at}},
            _PROJECTION,
        ).limit(_BATCH_SIZE)

        docs = await cursor.to_list(length=_BATCH_SIZE)
        if not docs:
            break

        applied_in_batch = 0
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            scanned += 1
            run_id = _clean_text(doc.get("run_id"))
            job_id = _clean_text(doc.get("job_id"))
            if not run_id:
                # בלי מזהה הרצה אין עדכון מוגן. נרשם כדי שלא ייעלם.
                logger.warning("job run without run_id skipped during orphan reconcile")
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
                applied_in_batch += 1
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

        if applied_in_batch == 0:
            # שום מסמך במנה לא עודכן, ולכן השליפה הבאה תחזיר את אותה מנה.
            break

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
