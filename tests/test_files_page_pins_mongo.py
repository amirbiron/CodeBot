"""נעיצת פתקים לעמוד הקבצים מול **מונגו אמיתי** — מה שהדמה ב-``tests/test_files_page_pins.py`` אינה יכולה לבדוק.

- **התוכנית.** ``files_page_pinned_filter`` הוא ``$type: "date"`` על השדה, ולכן על ``files_page_pinned_idx``
  הגבולות מדלגים על כל פתק שאינו נעוץ, והמיון (``FILES_PAGE_PINNED_SORT``) מגיע מהאינדקס — בלי ``SORT``.
  נמדד ב-explain על השאילתה **שהראוט שולח** (נרשמת בדרך), ועל הספירה של התקרה כפי ש-pymongo שולח אותה.
- **המרוץ.** הנעיצה היא כתיבה מותנית אחת. שתי נעיצות מקבילות של אותו פתק — רק אחת כותבת.
- **שני הבוטסטראפים.** הוובאפ (``_ensure_indexes``) וה-MCP (``_notes_coll``) בונים את אותו אינדקס באותו
  מפרט, בשני סדרי העלייה (``docs/dev/sticky_notes_extending_backend.rst``, "אכיפה שנבנית רק בצד אחד").
- **ההעברה לארכיון והשחזור** — מקצה לקצה, מול המסד.

**מדלגים רק על "אין שרת"** (``_note_threads_harness.mongo_reachable``): כתובת שגויה או אימות שנכשל מפילים.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("pymongo")
flask = pytest.importorskip("flask")

from bson import ObjectId  # noqa: E402
from bson.codec_options import CodecOptions, DatetimeConversion  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _note_threads_harness import insert_board, insert_note, mongo_reachable, temp_database  # noqa: E402

import sticky_notes_target as snt  # noqa: E402

USER, OTHER = 7, 8
FIELD = snt.FILES_PAGE_PIN_FIELD

pytestmark = pytest.mark.skipif(not mongo_reachable(), reason="דורש MONGODB_URL עם שרת מונגו נגיש")

#: גבולות האינדקס של ``$type: "date"`` כוללים את התאריך המרבי של BSON — ראו ``test_note_archive_mongo.py``.
_EXPLAIN_CODEC = CodecOptions(datetime_conversion=DatetimeConversion.DATETIME_AUTO, tz_aware=True)


@pytest.fixture
def db():
    with temp_database("codebot_files_pins_it_") as database:
        yield database


class _RecordingDb:
    """המסד האמיתי, ו-``find`` של ``sticky_notes`` נרשם — הפילטר, ההיטלה והמיון שהראוט שלח."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.finds: list[dict] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    def __getitem__(self, name: str) -> Any:
        return self._real[name]

    @property
    def sticky_notes(self) -> Any:
        recorder, real = self, self._real.sticky_notes

        class _Cursor:
            def __init__(self, cursor: Any, entry: dict) -> None:
                self._cursor, self._entry = cursor, entry

            def sort(self, keys: Any, *args: Any) -> "_Cursor":
                self._entry["sort"] = list(keys)
                self._cursor = self._cursor.sort(keys, *args)
                return self

            def __iter__(self):
                return iter(self._cursor)

        class _Coll:
            def __getattr__(self, name: str) -> Any:
                return getattr(real, name)

            def find(self, filter: Any = None, projection: Any = None, *args: Any, **kwargs: Any) -> Any:
                entry = {"filter": filter, "projection": projection, "sort": None}
                recorder.finds.append(entry)
                return _Cursor(real.find(filter, projection, *args, **kwargs), entry)

        return _Coll()


@pytest.fixture
def api(db, monkeypatch):
    """הבלופרינט האמיתי מול המסד הזמני, עם ``_ensure_indexes`` האמיתי — ובדיקה שהוא הושלם."""
    from webapp import sticky_notes_api

    recording = _RecordingDb(db)
    monkeypatch.setattr(sticky_notes_api, "get_db", lambda: recording)
    monkeypatch.setattr(sticky_notes_api, "_current_user_is_admin", lambda: False)
    sticky_notes_api._ensure_indexes()
    assert sticky_notes_api._INDEX_READY, "הבנייה של _ensure_indexes לא הושלמה מול מסד הבדיקה"

    app = flask.Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(sticky_notes_api.sticky_notes_bp)

    def client(user_id: int = USER):
        c = app.test_client()
        with c.session_transaction() as sess:
            sess["user_id"] = user_id
        return c

    return SimpleNamespace(module=sticky_notes_api, client=client, recording=recording, db=db)


def _plan_stages(explain: dict) -> tuple[list[str], dict]:
    planner = explain.get("queryPlanner") or explain["stages"][0]["$cursor"]["queryPlanner"]
    stats = explain.get("executionStats") or explain["stages"][0]["$cursor"]["executionStats"]
    plan = planner["winningPlan"]
    plan = plan.get("queryPlan", plan)
    out: list[str] = []

    def walk(node: dict) -> None:
        out.append(f"{node.get('stage')}:{node.get('indexName', '')}")
        if "inputStage" in node:
            walk(node["inputStage"])
        for child in node.get("inputStages", []) or []:
            walk(child)

    walk(plan)
    return out, stats


def _seed(db, user_id: int, *, pinned: int = 0, plain: int = 0) -> list[str]:
    """``pinned`` פתקי לוח נעוצים (זמני נעיצה עולים) ו-``plain`` פתקי לוח שאינם נעוצים."""
    now = datetime.now(timezone.utc)
    docs = [{"_id": ObjectId(), "user_id": user_id, "board_id": "b", "content": f"# נעוץ {i}\nגוף", "color": "yellow",
             FIELD: now + timedelta(seconds=i)} for i in range(pinned)]
    docs += [{"user_id": user_id, "board_id": "b", "content": "y" * 500} for _ in range(plain)]
    if docs:
        db.sticky_notes.insert_many(docs)
    return [str(d["_id"]) for d in docs[:pinned]]


# == התוכנית ==================================================================================


def test_the_list_the_route_sends_reads_only_pinned_notes_in_index_order(api, db):
    """בלי ``SORT``, ומה שנקרא הוא בדיוק מה שחוזר — גם כשיש למשתמש אלף פתקים שאינם נעוצים, ולמשתמש אחר
    נעוצים משלו. נופל על ``$exists: True`` (פתק שאינו נעוץ נשמר באינדקס כ-``null``) ועל מסד בלי האינדקס."""
    _seed(db, USER, pinned=3, plain=1000)
    _seed(db, OTHER, pinned=4, plain=50)

    res = api.client().get("/api/sticky-notes/files-page")
    body = res.get_json()

    assert res.status_code == 200 and body["count"] == 3, body
    assert [n["label"] for n in body["notes"]] == ["# נעוץ 0", "# נעוץ 1", "# נעוץ 2"]

    [sent] = [f for f in api.recording.finds if f["sort"] is not None]
    explain = db.command(
        "explain",
        {"find": "sticky_notes", "filter": sent["filter"], "projection": sent["projection"],
         "sort": dict(sent["sort"])},
        verbosity="executionStats", codec_options=_EXPLAIN_CODEC,
    )
    stages, stats = _plan_stages(explain)
    assert not any(s.startswith("SORT") for s in stages), stages
    assert "IXSCAN:files_page_pinned_idx" in stages, stages
    assert stats["totalKeysExamined"] == stats["totalDocsExamined"] == stats["nReturned"] == 3, stats


def test_the_cap_count_reads_only_the_pinned_notes(api, db):
    """``count_documents`` נשלח כ-``aggregate`` של ``$match`` ואחריו ``$group`` (pymongo 4.15.3). התנאי
    ``archived_at: None`` הוא שארית — ולכן נקראים רק המסמכים הנעוצים, ולא אלף הפתקים שלידם."""
    _seed(db, USER, pinned=2, plain=1000)
    query = snt.files_page_pinned_filter(USER)

    assert db.sticky_notes.count_documents(query) == 2
    explain = db.command(
        "explain",
        {"aggregate": "sticky_notes", "cursor": {},
         "pipeline": [{"$match": query}, {"$group": {"_id": 1, "n": {"$sum": 1}}}]},
        verbosity="executionStats", codec_options=_EXPLAIN_CODEC,
    )
    stages, stats = _plan_stages(explain)
    assert "IXSCAN:files_page_pinned_idx" in stages, stages
    assert stats["totalDocsExamined"] == 2, stats["totalDocsExamined"]


# == שני הבוטסטראפים ==========================================================================


def _index_keys(coll) -> dict:
    return {name: tuple((f, int(d)) for f, d in info["key"]) for name, info in coll.index_information().items()}


@pytest.mark.parametrize("webapp_first", [True, False], ids=["webapp-then-mcp", "mcp-then-webapp"])
def test_both_bootstraps_build_the_same_pinned_index_in_either_order(monkeypatch, webapp_first):
    from mcp_server.backend import ProductionBackend
    from webapp import sticky_notes_api

    with temp_database("codebot_files_pins_boot_") as database:
        monkeypatch.setattr(sticky_notes_api, "get_db", lambda: database)

        def webapp() -> None:
            sticky_notes_api.reset_index_state_for_tests()
            sticky_notes_api._ensure_indexes()

        def mcp() -> None:
            ProductionBackend(mongo_db=database)._notes_coll()

        for step in ((webapp, mcp) if webapp_first else (mcp, webapp)):
            step()
        keys = _index_keys(database.sticky_notes)

    assert keys["files_page_pinned_idx"] == (("user_id", 1), (FIELD, 1), ("_id", 1)), keys


# == הנעיצה מקצה לקצה =========================================================================


def test_two_concurrent_pins_of_one_note_write_once(api, db, monkeypatch):
    """שתי בקשות עוברות את הבדיקות, ורק אז מותר להן לכתוב (``Barrier`` לפני הספירה). אחת כותבת; השנייה
    עונה ``already_pinned`` בלי לכתוב — ואותו זמן נעיצה."""
    board = insert_board(db, USER)
    note = insert_note(db, USER, board_id=board, title="שם")
    gate = threading.Barrier(2, timeout=10)
    real_count = api.module._count_or_none

    def after_both_read(coll, query):
        gate.wait()
        return real_count(coll, query)

    monkeypatch.setattr(api.module, "_count_or_none", after_both_read)
    answers: list[dict] = []

    def go() -> None:
        answers.append(api.client().post(f"/api/sticky-notes/note/{note}/files-page-pin", json={}).get_json())

    workers = [threading.Thread(target=go) for _ in range(2)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(20)

    assert len(answers) == 2 and all(a["ok"] is True for a in answers), answers
    assert sorted(a["already_pinned"] for a in answers) == [False, True]
    stored = db.sticky_notes.find_one({"_id": ObjectId(note)})
    assert {a[FIELD] for a in answers} == {stored[FIELD].isoformat()}


def test_archiving_a_pinned_note_takes_it_off_the_files_page(api, db):
    board = insert_board(db, USER)
    note = insert_note(db, USER, board_id=board, title="שם")
    client = api.client()
    assert client.post(f"/api/sticky-notes/note/{note}/files-page-pin", json={}).status_code == 200
    assert client.get("/api/sticky-notes/files-page").get_json()["count"] == 1

    assert client.post(f"/api/sticky-notes/note/{note}/archive", json={}).status_code == 200

    assert FIELD not in db.sticky_notes.find_one({"_id": ObjectId(note)})
    assert client.get("/api/sticky-notes/files-page").get_json()["count"] == 0
    assert client.get(f"/api/sticky-notes/files-page/{note}").status_code == 404


def test_the_cap_and_the_device_limit_against_the_database(api, db):
    board = insert_board(db, USER)
    notes = [insert_note(db, USER, board_id=board, title=f"פ{i}") for i in range(6)]
    client = api.client()
    for note in notes[:2]:
        assert client.post(f"/api/sticky-notes/note/{note}/files-page-pin", json={"device_limit": 2}).status_code == 200
    # מכשיר שנכנסים בו שניים — מלא
    full = client.post(f"/api/sticky-notes/note/{notes[2]}/files-page-pin", json={"device_limit": 2})
    assert full.status_code == 409 and full.get_json()["device_limited"] is True
    # מכשיר רחב — עד ארבעה, ולא יותר
    for note in notes[2:4]:
        assert client.post(f"/api/sticky-notes/note/{note}/files-page-pin", json={}).status_code == 200
    capped = client.post(f"/api/sticky-notes/note/{notes[4]}/files-page-pin", json={"device_limit": 9})
    assert capped.status_code == 409 and capped.get_json()["max"] == 4
    assert [n["id"] for n in client.get("/api/sticky-notes/files-page").get_json()["notes"]] == notes[:4]


def test_a_pinned_note_survives_backup_and_restore_into_an_empty_account(api, db):
    from services.personal_backup_service import PersonalBackupService

    board = insert_board(db, USER, name="לוח עבודה")
    note = insert_note(db, USER, board_id=board, content="נעוץ")
    api.client().post(f"/api/sticky-notes/note/{note}/files-page-pin", json={})
    service = PersonalBackupService(SimpleNamespace(db=db))
    exported = service._export_sticky_notes(USER)
    pinned_at = db.sticky_notes.find_one({"_id": ObjectId(note)})[FIELD]

    db.sticky_notes.delete_many({"user_id": USER})
    errors: list[str] = []
    assert service._restore_sticky_notes(USER, exported, errors) == 1
    restored = db.sticky_notes.find_one({"user_id": USER, "content": "נעוץ"})

    assert errors == []
    assert restored["board_id"] == board
    assert restored[FIELD].replace(tzinfo=timezone.utc) == pinned_at.replace(tzinfo=timezone.utc)
    assert api.client().get("/api/sticky-notes/files-page").get_json()["count"] == 1
