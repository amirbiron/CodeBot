"""האוסף ``job_runs`` — שמו, חלון השמירה שלו, והאינדקסים שהשאילתות בקוד דורשות.

הקובץ הזה הוא **מקור האמת היחיד** לאוסף. ‏``DatabaseManager._create_indexes``
מייבא ממנו; עד אישיו #3331 הוא לא יובא מאף מקום, ולכן ה-TTL שהתיעוד הבטיח
(``docs/observability/background-jobs-monitor.rst``) פשוט לא היה קיים במסד —
318,797 מסמכים בלי שום מחיקה. קובץ הגדרות שאיש אינו מייבא אינו הגדרה, הוא
תיאור של כוונה.

**שדה הזמן הוא ``started_at``.** נכתב בכל שמירה ב-``services/job_tracker.py``
(``_persist_run``). ‏``ended_at`` קיים רק כשההרצה הסתיימה, ולכן אינו מתאים
ל-TTL: *"If a document does not contain the indexed field, the document will not
expire"* (מקור: https://www.mongodb.com/docs/manual/core/index-ttl/) — הרצה
תקועה הייתה נשמרת לנצח דווקא.

**האינדקסים נגזרים מהשאילתות שקיימות בקוד, לא מהתיעוד:**

=========================================================  ==============================  =========================
שאילתה                                                      איפה                            מה משרת אותה
=========================================================  ==============================  =========================
``find_one({run_id})``                                     ``job_tracker.get_run``,        ``idx_job_runs_id``
                                                           ``webapp api_job_run_detail``
``find({job_id}).sort(started_at desc).limit(20)``         ``job_tracker``,                ``idx_job_runs_job_time``
                                                           ``webapp api_job_detail``
``find({job_id, status}).sort(started_at desc)``           ``webapp api_job_detail``       ``idx_job_runs_job_time``
``find({status:"running"}).sort(started_at desc)``         ``webapp api_jobs_active``      ``idx_job_runs_status_time``
``find({status:"running", started_at:{$lt}})``             ``main.py`` (ניטור תקיעות),      ``idx_job_runs_status_time``
                                                           ``job_orphan_reconciler``
``aggregate($match started_at>=since, $group job_id)``     ``webapp api_jobs``             ``idx_job_runs_ttl``
=========================================================  ==============================  =========================

**שתי שאילתות נשארות בלי אינדקס ייעודי, במכוון:**

- ``find({status:{$in:[completed,failed,skipped]}, ended_at:{$gte}}).sort(ended_at desc)``
  (``webapp api_jobs_active``). ‏``$in`` על התחילית יחד עם מיון על השדה הבא הוא
  בדיוק המקרה שבו אי אפשר לקבוע מהקוד אם המתכנן בוחר explode-for-sort או מיון
  בזיכרון — וזה נמדד ב-``executionStats`` מול קלאסטר, לא מנוחש. עד שיימדד,
  ה-TTL הוא מה שחוסם את הגודל.
- ``find({status:"failed"}).sort(started_at desc).limit(10)``
  (``chatops/jobs_commands.py``) — משרת את ``idx_job_runs_status_time``.

**שני שדות נכתבים על ידי מי שאינו ההרצה עצמה.** ‏``failure_reason`` נכתב
בפיוס (``services/job_orphan_reconciler.py``) ומבדיל הרצה שנסגרה מבחוץ
מג'וב שנפל בקוד שלו; ``_persist_run`` מנקה אותו בכל כתיבה של ההרצה עצמה,
כדי שלא יישאר ייחוס חיצוני על רשומה שדיווחה על עצמה. ‏``owner_id`` נכתב
ב-``_persist_run`` ומזהה את המופע שהריץ. שניהם נקראים ב-
``webapp/app.py:_job_run_doc_to_dict``, ו-``failure_reason`` גם ב-
``chatops/jobs_commands.py``.

**אינדקס על ``user_id`` אינו נוצר.** ‏``user_id`` נכתב ומוצג, ואף שאילתה בריפו
אינה מסננת לפיו. אינדקס בלי קורא עולה בכל כתיבה ולא מחזיר דבר.

⚠️ ``idx_job_runs_ttl`` הוא אינדקס TTL: מרגע יצירתו מונגו מוחקת כל הרצה ישנה
מהחלון, בסבב שרץ אחת ל-60 שניות. זו מחיקת נתונים בפועל, במכוון. המשמעות
המעשית: קישור ``/jobs/monitor?run_id=...`` שנשלח בטלגרם חי בדיוק כאורך החלון,
והרצה שנתקעה יותר מהחלון תימחק בזמן שהיא עדיין ``running``.
"""

from __future__ import annotations

import os

JOB_RUNS_COLLECTION = "job_runs"

#: ברירת המחדל של חלון השמירה, בימים. 30 ולא 7 (הערך שהתיעוד הבטיח) כי ארבעה
#: קוראים עובדים בלי שום חסם זמן — "20 ההרצות האחרונות" של ג'וב שרץ פעם בשבועיים,
#: ‏"10 הכשלונות האחרונים" ב-ChatOps, וקישורי ``run_id`` קבועים שמחולקים בטלגרם.
JOB_RUNS_TTL_DAYS_DEFAULT = 30


def job_runs_ttl_seconds() -> int:
    """חלון השמירה של ``job_runs`` בשניות, לפי ``JOB_RUNS_TTL_DAYS``.

    נקרא בזמן יצירת האינדקס ולא בזמן הייבוא, כדי שערך שמוגדר אחרי עליית המודול
    (ובבדיקות) ייקרא בפועל.
    """
    try:
        days = int(os.getenv("JOB_RUNS_TTL_DAYS", "") or JOB_RUNS_TTL_DAYS_DEFAULT)
    except (TypeError, ValueError):
        days = JOB_RUNS_TTL_DAYS_DEFAULT
    # 0 או ערך שלילי היו יוצרים אינדקס שמוחק כל מסמך מיד. חוסמים מלמטה.
    return max(1, days) * 24 * 3600


def job_runs_indexes() -> list[dict]:
    """הגדרות האינדקסים, בצורה ש-``safe_create_index`` מקבלת.

    ``expire_after_seconds`` מופיע רק על אינדקס **חד-שדה**: *"TTL indexes are
    single-field indexes. Compound indexes do not support TTL and ignore the
    expireAfterSeconds option"*
    (מקור: https://www.mongodb.com/docs/manual/core/index-ttl/).

    ⚠️ **התיעוד אומר "ignore", והשרת עושה משהו אחר.** נמדד מול mongod 7.0.14:
    היצירה נדחית ב-``OperationFailure`` — *"TTL indexes are single-field indexes,
    compound indexes do not support TTL"*. בשתי ההתנהגויות המסקנה זהה — אינדקס
    מורכב אינו נושא TTL — אבל מי שמסתמך על "ignore" יקבל אינדקס שלא נוצר בכלל.
    """
    return [
        {
            "keys": [("run_id", 1)],
            # מזהה ההרצה: עדכוני סטטוס וקישורים עמוקים עובדים דרכו.
            "name": "idx_job_runs_id",
            "unique": True,
        },
        {
            "keys": [("job_id", 1), ("started_at", -1)],
            "name": "idx_job_runs_job_time",
        },
        {
            "keys": [("status", 1), ("started_at", -1)],
            "name": "idx_job_runs_status_time",
        },
        {
            # עולה ולא יורד: אינדקס חד-שדה נסרק לשני הכיוונים, ולכן המיון היורד
            # ב-``$group`` עדיין נתמך, והכיוון אינו משנה ל-TTL.
            "keys": [("started_at", 1)],
            "name": "idx_job_runs_ttl",
            "expire_after_seconds": job_runs_ttl_seconds(),
            # בלי אכיפה, שינוי של JOB_RUNS_TTL_DAYS היה מתנגש עם האינדקס הקיים
            # ונבלע כאזהרה — ה-retention הישן היה ממשיך למחוק לפי הערך הישן.
            "enforce": True,
        },
    ]
