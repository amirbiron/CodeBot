"""אינדקסים ו-TTL לאוסף ``job_runs`` (אישיו #3331).

``database/job_runs_collection.py`` הגדיר TTL של 7 ימים, התיעוד הבטיח אותו, ו-
grep הראה שהקובץ **לא מיובא מאף מקום**. התוצאה בפרודקשן: 318,797 מסמכים בלי
אינדקס TTL אחד. הבדיקות כאן מקבעות את שתי הטענות שנשברו שם — שההגדרות באמת
מגיעות ליוצר האינדקסים, ושה-TTL יושב על השדה שהכותב באמת כותב.
"""

from __future__ import annotations

import types
from datetime import datetime, timezone

from database.job_runs_collection import (
    JOB_RUNS_COLLECTION,
    JOB_RUNS_TTL_DAYS_DEFAULT,
    job_runs_indexes,
    job_runs_ttl_seconds,
)
from database.manager import DatabaseManager


class _Coll:
    def create_indexes(self, indexes):
        return None

    def list_indexes(self):
        return []


class _DB:
    def __getitem__(self, name):
        return _Coll()


def _requested_indexes() -> list[tuple]:
    """כל קריאה ל-``safe_create_index`` שיצאה מ-``_create_indexes``."""
    requested: list[tuple] = []
    fake_self = types.SimpleNamespace(
        collection=_Coll(),
        large_files_collection=_Coll(),
        db=_DB(),
        backup_ratings_collection=_Coll(),
        internal_shares_collection=_Coll(),
        community_library_collection=_Coll(),
        snippets_collection=_Coll(),
        safe_create_index=lambda collection, keys, **kwargs: requested.append((collection, list(keys), kwargs)),
    )
    DatabaseManager._create_indexes(fake_self)
    return requested


def _job_runs_requests() -> list[tuple]:
    return [row for row in _requested_indexes() if row[0] == JOB_RUNS_COLLECTION]


class TestWiring:
    def test_the_definitions_reach_the_index_creator(self):
        """הכשל המקורי: קובץ הגדרות שאף אחד לא מייבא.

        בלי החיווט הזה הקובץ הוא תיאור של כוונה, והתיעוד מבטיח TTL שאינו קיים.
        """
        names = [kwargs.get("name") for _, _, kwargs in _job_runs_requests()]
        assert names == [
            "idx_job_runs_id",
            "idx_job_runs_job_time",
            "idx_job_runs_status_time",
            "idx_job_runs_ttl",
        ]

    def test_a_ttl_index_is_actually_requested(self):
        ttl = [(keys, kwargs) for _, keys, kwargs in _job_runs_requests() if kwargs.get("expire_after_seconds")]
        assert len(ttl) == 1, "job_runs נשאר בלי TTL — זה בדיוק המצב שאישיו #3331 מתאר"
        keys, kwargs = ttl[0]
        assert kwargs["expire_after_seconds"] == JOB_RUNS_TTL_DAYS_DEFAULT * 24 * 3600
        # בלי enforce, שינוי של JOB_RUNS_TTL_DAYS מתנגש עם האינדקס הקיים
        # ונבלע כאזהרה — החלון הישן ממשיך למחוק.
        assert kwargs["enforce"] is True

    def test_the_unique_run_id_index_survived_the_move(self):
        """הקישורים העמוקים (``?run_id=``) ועדכוני הסטטוס עוברים דרכו."""
        unique = [kwargs for _, _, kwargs in _job_runs_requests() if kwargs.get("unique")]
        assert [k["name"] for k in unique] == ["idx_job_runs_id"]


class TestTTLShape:
    def test_ttl_is_single_field_and_on_started_at(self):
        """אינדקס מורכב אינו יכול לשאת TTL.

        *"TTL indexes are single-field indexes. Compound indexes do not support
        TTL and ignore the expireAfterSeconds option"*
        (מקור: https://www.mongodb.com/docs/manual/core/index-ttl/); מול mongod
        7.0.14 נמדד שהשרת דוחה יצירה כזו בשגיאה. כך או כך, TTL על האינדקס
        המורכב לא היה מוחק מסמך אחד.
        """
        ttl = [spec for spec in job_runs_indexes() if spec.get("expire_after_seconds")]
        assert len(ttl) == 1
        assert ttl[0]["keys"] == [("started_at", 1)]

    def test_the_ttl_field_is_the_one_the_writer_writes(self):
        """``started_at`` ולא ``ended_at``, ולא שם שנשמע נכון.

        *"If a document does not contain the indexed field, the document will not
        expire"* — ולכן TTL על ``ended_at`` היה משאיר בדיוק את ההרצות התקועות.
        הבדיקה עוברת דרך הכותב עצמו ולא דרך רשימת שדות שמישהו העתיק.
        """
        from services.job_tracker import JobRun, JobStatus, JobTracker

        persisted: dict = {}

        class _RunsColl:
            def update_one(self, _filter, update, **_kwargs):
                persisted.update(update["$set"])

        fake_tracker = types.SimpleNamespace(
            db=types.SimpleNamespace(client={"db": {"job_runs": _RunsColl()}}, db_name="db")
        )
        run = JobRun(
            run_id="r1",
            job_id="j1",
            started_at=datetime.now(timezone.utc),
            status=JobStatus.RUNNING,
        )
        JobTracker._persist_run(fake_tracker, run)

        assert "started_at" in persisted and persisted["started_at"] is not None
        # ההרצה עדיין רצה — השדה השני ריק, ולכן אינו יכול לשאת TTL
        assert persisted.get("ended_at") is None
        ttl_field = [spec for spec in job_runs_indexes() if spec.get("expire_after_seconds")][0]["keys"][0][0]
        assert ttl_field in persisted

    def test_no_index_without_a_reader(self):
        """``user_id`` נכתב ומוצג, ואף שאילתה בריפו אינה מסננת לפיו."""
        keyed_fields = {field for spec in job_runs_indexes() for field, _ in spec["keys"]}
        assert "user_id" not in keyed_fields


class TestRetentionWindow:
    def test_default_is_thirty_days(self, monkeypatch):
        monkeypatch.delenv("JOB_RUNS_TTL_DAYS", raising=False)
        assert job_runs_ttl_seconds() == 30 * 24 * 3600

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("JOB_RUNS_TTL_DAYS", "7")
        assert job_runs_ttl_seconds() == 7 * 24 * 3600

    def test_garbage_falls_back_instead_of_crashing_startup(self, monkeypatch):
        """הקריאה הזו רצה בתוך יצירת האינדקסים בעלייה של התהליך."""
        monkeypatch.setenv("JOB_RUNS_TTL_DAYS", "מחר")
        assert job_runs_ttl_seconds() == JOB_RUNS_TTL_DAYS_DEFAULT * 24 * 3600

    def test_zero_does_not_become_delete_everything(self, monkeypatch):
        """``expireAfterSeconds: 0`` מוחק כל מסמך בסבב הניקוי הבא."""
        monkeypatch.setenv("JOB_RUNS_TTL_DAYS", "0")
        assert job_runs_ttl_seconds() == 24 * 3600
