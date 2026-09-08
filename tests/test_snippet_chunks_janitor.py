"""ג'וב ניקוי הצ'אנקים היתומים.

הרקע (אישו #3332): שני מקורות של יתומים אינם עוברים דרך קוד אפליקציה בכלל.

1. **פקיעת סל המיחזור** נעשית ב-TTL index על ``deleted_expires_at``. מונגו
   מוחק את מסמך הקובץ בצד השרת, ואף שורת קוד שלנו לא רצה.
2. **גרסאות שהוחלפו** — שמירת גרסה חדשה אינה מכבה את הקודמת, ולכן כל גרסה
   היסטורית נשארת מאונדקסת. נמדד בפרודקשן: ל-``Programming.svg`` שלושה
   מסמכי צ'אנק פעילים, אחד לכל גרסה.

הדמות כאן מממשת בפועל את השאילתות שהג'וב מריץ, ולא מחזירה תשובה קבועה —
אחרת הטסט היה עובר גם על ג'וב שאינו מסנן כלום.
"""

import functools
import sys

import pytest
from bson import ObjectId

import services.snippet_chunks_janitor as janitor


class _Result:
    def __init__(self, deleted=0):
        self.deleted_count = deleted


class _Chunks:
    def __init__(self, docs):
        self.docs = list(docs)
        self.deleted_filters = []

    def aggregate(self, pipeline):
        assert "$group" in pipeline[0], pipeline
        groups = {}
        for doc in self.docs:
            key = (doc["userId"], doc["snippetId"])
            groups[key] = groups.get(key, 0) + 1
        return [
            {"_id": {"userId": u, "snippetId": s}, "chunks": n}
            for (u, s), n in groups.items()
        ]

    def delete_many(self, query):
        self.deleted_filters.append(query)
        user_id = query["userId"]
        ids = set(query["snippetId"]["$in"])
        before = len(self.docs)
        self.docs = [
            d for d in self.docs
            if not (d["userId"] == user_id and d["snippetId"] in ids)
        ]
        return _Result(deleted=before - len(self.docs))


def _mongo_cmp(a, b):
    """השוואה בסגנון מונגו: ``None`` ממוין לפני כל ערך אחר."""
    if a == b:
        return 0
    if a is None:
        return -1
    if b is None:
        return 1
    return -1 if a < b else 1


class _Files:
    """דמה של ``code_snippets`` שמבצעת את הצינור **כפי שהוא נכתב**.

    זו הנקודה: הגרסה הקודמת של הדמה מימשה מחדש בפייתון את "הגרסה האחרונה
    מנצחת" — מיון קשיח לפי ``-version`` — בלי להסתכל בכלל על שלבי ה-``$sort``
    וה-``$group`` שהג'וב שולח. משמעות הדבר שאם סדר המיון בג'וב היה נשבר
    (למשל ``version: 1`` במקום ``-1``), הטסטים היו ממשיכים לעבור, כי הדמה
    הייתה ממילא מחזירה את התשובה הנכונה בכוחות עצמה. טסט שאינו מסוגל להיכשל
    אינו ראיה.

    כאן המיון והקיבוץ **נגזרים** מהצינור: אם הג'וב ישנה כיוון מיון, ישמיט
    שלב, או יחליף ``$first`` — הדמה תחזיר תשובה אחרת והטסטים ייפלו.
    """

    def __init__(self, docs):
        self.docs = list(docs)
        self.pipelines = []
        self.aggregate_kwargs = []

    def find(self, query, projection=None):
        wanted = set(query["_id"]["$in"])
        return [dict(d) for d in self.docs if d["_id"] in wanted]

    def aggregate(self, pipeline, **kwargs):
        self.pipelines.append(pipeline)
        self.aggregate_kwargs.append(kwargs)

        stages = {}
        for stage in pipeline:
            name, body = next(iter(stage.items()))
            assert name not in stages, f"stage {name} appears twice: {pipeline}"
            stages[name] = body

        # השלבים חייבים להיות שם. ``KeyError`` כאן = הצינור השתנה והטסט צריך
        # לדעת על זה, לא לעקוף בשקט.
        match = stages["$match"]
        sort_spec = stages["$sort"]
        group = stages["$group"]

        rows = [
            dict(d) for d in self.docs
            if all(
                (d.get(field) in cond["$in"]) if isinstance(cond, dict) and "$in" in cond
                else (d.get(field) == cond)
                for field, cond in match.items()
            )
        ]

        # מיון לפי המפרט המוצהר בלבד, כולל כיוון לכל שדה.
        def _cmp(a, b):
            for field, direction in sort_spec.items():
                verdict = _mongo_cmp(a.get(field), b.get(field))
                if verdict:
                    return verdict * (1 if direction >= 0 else -1)
            return 0

        rows.sort(key=functools.cmp_to_key(_cmp))

        # ``$group`` עם ``$first``: הראשון אחרי המיון מנצח.
        key_spec = group["_id"]
        accumulators = {k: v for k, v in group.items() if k != "_id"}

        out, seen = [], {}
        for row in rows:
            key = tuple(
                row.get(str(expr).lstrip("$")) for expr in key_spec.values()
            )
            if key in seen:
                continue
            entry = {"_id": {name: row.get(str(expr).lstrip("$"))
                             for name, expr in key_spec.items()}}
            for out_name, acc in accumulators.items():
                op, source = next(iter(acc.items()))
                assert op == "$first", f"unsupported accumulator {op}"
                entry[out_name] = row.get(str(source).lstrip("$"))
            seen[key] = True
            out.append(entry)
        return out


class _DB:
    def __init__(self, chunks, files):
        self._c = {"snippet_chunks": chunks, "code_snippets": files}

    def __getitem__(self, name):
        return self._c[name]


LIVE = ObjectId()
OLD_VERSION = ObjectId()
TRASHED = ObjectId()
GONE = ObjectId()


def _build(monkeypatch, chunk_docs, file_docs):
    chunks = _Chunks(chunk_docs)
    files = _Files(file_docs)
    monkeypatch.setattr(janitor, "_get_raw_db", lambda: _DB(chunks, files))
    return chunks, files


@pytest.fixture()
def world(monkeypatch):
    chunk_docs = (
        [{"userId": 7, "snippetId": LIVE}] * 3
        + [{"userId": 7, "snippetId": OLD_VERSION}] * 2
        + [{"userId": 7, "snippetId": TRASHED}] * 4
        + [{"userId": 7, "snippetId": GONE}] * 5
    )
    file_docs = [
        {"_id": LIVE, "user_id": 7, "file_name": "a.py", "is_active": True, "version": 2},
        {"_id": OLD_VERSION, "user_id": 7, "file_name": "a.py", "is_active": True, "version": 1},
        {"_id": TRASHED, "user_id": 7, "file_name": "b.py", "is_active": False, "version": 1},
        # GONE אינו קיים ב-code_snippets כלל — פקע ב-TTL של סל המיחזור.
    ]
    return _build(monkeypatch, chunk_docs, file_docs)


def test_orphans_are_deleted_and_the_live_version_survives(world):
    chunks, _files = world

    report = janitor.cleanup_orphan_snippet_chunks()

    assert report["ok"] is True
    assert report["orphan_snippets"] == 3  # old version + trashed + gone
    assert report["deleted_chunks"] == 2 + 4 + 5
    assert [d["snippetId"] for d in chunks.docs] == [LIVE] * 3


def test_superseded_version_is_an_orphan(world):
    """זה החלק שהגדרת "אין מסמך" הייתה מפספסת: המסמך קיים, פעיל, ופשוט
    אינו הגרסה האחרונה."""
    chunks, _files = world
    janitor.cleanup_orphan_snippet_chunks()
    assert OLD_VERSION not in {d["snippetId"] for d in chunks.docs}


def test_dry_run_reports_without_deleting(world):
    chunks, _files = world

    report = janitor.cleanup_orphan_snippet_chunks(dry_run=True)

    assert report["orphan_snippets"] == 3
    assert report["deleted_chunks"] == 0
    assert len(chunks.docs) == 14, "dry run deleted data"


def test_every_delete_is_scoped_to_a_user(world):
    """מחיקה חוצת-משתמשים היא בדיוק סוג התקלה שאסור לג'וב תחזוקה."""
    chunks, _files = world
    janitor.cleanup_orphan_snippet_chunks()

    assert chunks.deleted_filters
    for query in chunks.deleted_filters:
        assert "userId" in query and "snippetId" in query


def test_non_objectid_snippet_ids_are_reported_not_deleted(monkeypatch):
    """מזהה מסוג אחר לא יימצא ב-``$lookup`` ולכן ייראה יתום.

    זה בדיוק הכשל השקט שאסור לנו — מדווחים ולא מוחקים.
    """
    chunks, _files = _build(
        monkeypatch,
        [{"userId": 7, "snippetId": "legacy-string-id"}] * 3,
        [],
    )

    report = janitor.cleanup_orphan_snippet_chunks()

    assert report["skipped_non_objectid"] == 1
    assert report["deleted_chunks"] == 0
    assert len(chunks.docs) == 3


def test_no_database_is_reported_as_not_ok(monkeypatch):
    """``ok=False`` אינו "אין מה לנקות" — הוא "לא הצלחתי לבדוק".

    ה-job runner ב-main.py מסתמך על זה כדי לא לרשום ריצה כושלת כהצלחה.
    """
    monkeypatch.setattr(janitor, "_get_raw_db", lambda: None)

    report = janitor.cleanup_orphan_snippet_chunks()

    assert report["ok"] is False
    assert report["reason"] == "no_db"


def test_empty_collection_is_ok(monkeypatch):
    _build(monkeypatch, [], [])
    report = janitor.cleanup_orphan_snippet_chunks()
    assert report["ok"] is True and report["orphan_snippets"] == 0


# --- מבנה הצינור עצמו -----------------------------------------------------


def test_latest_version_pipeline_declares_the_sort_and_group_it_relies_on(world):
    """הכלל "הגרסה האחרונה מנצחת" חייב להיות בצינור, לא בקוד הפייתון שסביבו.

    בלי ה-``$sort`` היורד ו-``$first`` המתאים לו, מונגו היה מחזיר גרסה
    שרירותית — והג'וב היה מוחק את הצ'אנקים של הגרסה החיה.
    """
    _chunks, files = world
    janitor.cleanup_orphan_snippet_chunks()

    assert files.pipelines, "the janitor never asked which version is the latest"
    stages = {}
    for stage in files.pipelines[0]:
        name, body = next(iter(stage.items()))
        stages[name] = body

    assert set(stages) == {"$match", "$sort", "$group"}, stages
    assert stages["$match"]["is_active"] is True

    sort_spec = stages["$sort"]
    assert sort_spec["version"] == -1, "newest version must sort first"
    assert sort_spec["updated_at"] == -1, "tie-break on version must prefer newer"
    assert sort_spec["_id"] == -1, "final tie-break must be deterministic"
    # המיון חייב לקבץ קודם לפי מפתח הקיבוץ, אחרת ``$first`` לוקח שורה של קובץ אחר.
    assert list(sort_spec)[:2] == ["user_id", "file_name"], sort_spec

    group = stages["$group"]
    assert group["_id"] == {"user_id": "$user_id", "file_name": "$file_name"}
    assert group["latest"] == {"$first": "$_id"}


def test_group_stage_asks_the_database_to_deduplicate(world):
    """``$group`` על הצ'אנקים ולא ``distinct``: ``distinct`` מוגבל ל-16MB."""
    chunks, _files = world
    janitor.cleanup_orphan_snippet_chunks()
    assert chunks.docs == [{"userId": 7, "snippetId": LIVE}] * 3


# --- בעלות חוצת-משתמשים (K12) --------------------------------------------


def test_chunk_pointing_at_another_users_snippet_is_deleted(monkeypatch):
    """הפילטר של ``$vectorSearch`` הוא על ``userId`` של הצ'אנק.

    צ'אנק של משתמש 7 שמצביע על קובץ של משתמש 9 היה צף בתוצאות של 7 עם תוכן
    של 9. השארתו היא הסיכון, לא מחיקתו.
    """
    foreign = ObjectId()
    chunks, _files = _build(
        monkeypatch,
        [{"userId": 7, "snippetId": foreign}] * 4,
        [{"_id": foreign, "user_id": 9, "file_name": "secret.py",
          "is_active": True, "version": 1}],
    )

    report = janitor.cleanup_orphan_snippet_chunks()

    assert report["ownership_mismatch"] == 1
    assert report["deleted_chunks"] == 4
    assert chunks.docs == []


def test_active_snippet_without_a_file_name_is_quarantined_not_deleted(monkeypatch):
    """רשומה פגומה: פעילה, אבל בלי שם קובץ.

    היא אינה נכנסת לשלב "הגרסה האחרונה", ולכן ``latest`` לעולם לא יכיל אותה.
    היעדר המפתח **אינו** ראיה שהצ'אנקים יתומים — במקרה מפוקפק לא מוחקים.
    """
    broken = ObjectId()
    chunks, _files = _build(
        monkeypatch,
        [{"userId": 7, "snippetId": broken}] * 6,
        [{"_id": broken, "user_id": 7, "file_name": "", "is_active": True, "version": 1}],
    )

    report = janitor.cleanup_orphan_snippet_chunks()

    assert report["quarantined_no_file_name"] == 1
    assert report["orphan_snippets"] == 0
    assert report["deleted_chunks"] == 0
    assert len(chunks.docs) == 6


# --- ריצה בלי bson --------------------------------------------------------


def test_missing_bson_fails_closed(monkeypatch):
    """בלי ``bson`` אי אפשר לדעת אם מזהה הוא ``ObjectId``.

    fail-closed: לא מוחקים. ההיפך — להניח "כן ObjectId" — היה מכניס מזהים
    לא ידועים למסלול המחיקה בדיוק כשהיכולת לבדוק אותם אבדה.
    """
    # ``_is_object_id`` מייבא את ``bson`` בתוך הפונקציה, ולכן מדמים כאן את
    # ה-``ImportError`` עצמו: ``None`` ב-``sys.modules`` גורם ל-import להיכשל.
    monkeypatch.setitem(sys.modules, "bson", None)

    chunks, _files = _build(monkeypatch, [{"userId": 7, "snippetId": GONE}] * 3, [])
    report = janitor.cleanup_orphan_snippet_chunks()

    assert report["skipped_non_objectid"] == 1
    assert report["deleted_chunks"] == 0
    assert len(chunks.docs) == 3


# --- allowDiskUse ---------------------------------------------------------


class _ChunksWithDiskUse(_Chunks):
    """דמה שמקבלת ``allowDiskUse`` — כמו pymongo אמיתי."""

    def __init__(self, docs):
        super().__init__(docs)
        self.aggregate_kwargs = []

    def aggregate(self, pipeline, **kwargs):
        self.aggregate_kwargs.append(kwargs)
        return super().aggregate(pipeline)


def test_group_stage_is_allowed_to_spill_to_disk(monkeypatch):
    """``$group`` מוגבל ל-100MB בזיכרון, והוא רץ **לפני** כל ה-batching.

    בלי ``allowDiskUse`` הג'וב היה מפסיק לנקות בדיוק כשהקולקציה גדלה מספיק
    כדי שיהיה מה לנקות בה.
    """
    chunks = _ChunksWithDiskUse([{"userId": 7, "snippetId": GONE}] * 2)
    files = _Files([])
    monkeypatch.setattr(janitor, "_get_raw_db", lambda: _DB(chunks, files))

    report = janitor.cleanup_orphan_snippet_chunks()

    assert chunks.aggregate_kwargs == [{"allowDiskUse": True}]
    assert report["ok"] is True


def test_falls_back_when_the_driver_rejects_allow_disk_use(world):
    """דמות ומנהלים ישנים לא מקבלים את הפרמטר; ``TypeError`` אינו כשל אמיתי."""
    chunks, _files = world
    report = janitor.cleanup_orphan_snippet_chunks()
    assert report["ok"] is True and report["orphan_snippets"] == 3
