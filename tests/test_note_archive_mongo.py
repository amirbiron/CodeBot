"""ארכיון הפתקים מול **מונגו אמיתי** — מה שהדמה ב-``tests/test_note_archive.py`` אינה יכולה לבדוק.

שלושה דברים כאן אינם בקוד אלא בהתנהגות של המסד, ולכן רק מסד אמיתי עונה עליהם:

- **התוכנית.** ``active_notes_filter`` כותב ``archived_at: None`` ולא ``$exists: False``, ו-
  ``archived_notes_filter`` כותב ``$type: "date"`` — כי רק הצורות האלה נענות מהאינדקס
  ``user_archived_idx`` בלי לקרוא אף מסמך (COUNT_SCAN). ספירת 1000 רצה בכל יצירת פתק, ולכן זה
  נמדד כאן ב-explain, על השאילתות **שהקוד שולח** ולא על עותק שלהן.
- **האינדקסים הייחודיים.** "ארכיון הוא יעד חדש": ההעברה מוחקת את ``board_id``, וכך השם שהפתק
  החזיק בלוח משתחרר. את זה אוכף אינדקס ייחודי-חלקי, שקיים רק במסד.
- **המרוץ.** ההעברה היא כתיבה מותנית אחת (``find_one_and_update`` עם ``archived_at: None``
  בפילטר). שתי בקשות מקבילות — רק אחת כותבת. ``threading.Barrier`` מכריח את שתיהן לעבור את
  הקריאה לפני שאחת מהן כותבת, כך שהחלון באמת פתוח (``claude-md-snippets/testing.md``).

**מדלגים רק על "אין שרת"** (``_note_threads_harness.mongo_reachable``): כתובת שגויה או אימות
שנכשל מפילים, כי הם תקלת תצורה ולא היעדר שירות.
"""

from __future__ import annotations

import json
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
from _note_threads_harness import (  # noqa: E402
    insert_board,
    insert_file,
    insert_note,
    mongo_reachable,
    temp_database,
)

import note_threads as nt  # noqa: E402

USER, OTHER = 7, 8

pytestmark = pytest.mark.skipif(not mongo_reachable(), reason="דורש MONGODB_URL עם שרת מונגו נגיש")

#: גבולות האינדקס של ``$type: "date"`` כוללים את התאריך המרבי של BSON, שאינו נכנס ל-``datetime``
#: של פייתון — ובלי ``DATETIME_AUTO`` הפענוח של תשובת ה-explain זורק ``InvalidBSON``.
_EXPLAIN_CODEC = CodecOptions(datetime_conversion=DatetimeConversion.DATETIME_AUTO, tz_aware=True)


@pytest.fixture
def db():
    with temp_database("codebot_archive_it_") as database:
        yield database


class _RecordingDb:
    """המסד האמיתי, ו-``find`` ו-``aggregate`` של ``sticky_notes`` נרשמים — הפילטר, ההיטלה והמיון,
    או הצינור, שהראוט שלח."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.finds: list[dict] = []
        self.aggregates: list[list] = []

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

            def aggregate(self, pipeline: Any, *args: Any, **kwargs: Any) -> Any:
                recorder.aggregates.append(pipeline)
                return real.aggregate(pipeline, *args, **kwargs)

        return _Coll()


@pytest.fixture
def api(db, monkeypatch):
    """הבלופרינט האמיתי מול המסד הזמני, עם ``_ensure_indexes`` האמיתי — ובדיקה שהוא הושלם.

    מצב "האינדקסים מוכנים" מתאפס לפני כל בדיקה בפיקסצ'ר האוטומטי ב-``conftest.py`` שבשורש.
    """
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


def _archive(client, note_id: str, **body) -> Any:
    return client.post(f"/api/sticky-notes/note/{note_id}/archive", json=body)


def _plan_stages(explain: dict) -> tuple[list[str], dict]:
    """שמות השלבים בתוכנית הזוכה, ו-``executionStats`` — בשתי צורות התשובה של explain."""
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


def _seed(db, user_id: int, *, archived: int = 0, active: int = 0, board: str = "other") -> None:
    now = datetime.now(timezone.utc)
    docs = [{"user_id": user_id, "content": "x", "title": f"א{i}", "archived_at": now - timedelta(seconds=i)}
            for i in range(archived)]
    docs += [{"user_id": user_id, "content": "y", "board_id": board} for _ in range(active)]
    if docs:
        db.sticky_notes.insert_many(docs)


# == התוכנית ==================================================================================


def test_both_counts_are_answered_from_the_index_without_reading_a_note(api, db):
    """ספירת התקרה היא ``count_documents``, ש-pymongo שולח כ-``aggregate`` של ``$match`` ואחריו
    ``$group`` (pymongo 4.15.3, ``synchronous/collection.py``, ``count_documents``). זו השאילתה
    שנמדדת כאן — ``COUNT_SCAN`` על ``user_archived_idx``, ואפס מסמכים שנקראו.

    נופל על ``$exists: False`` (נמדד: FETCH של כל הפתקים), ועל מסד בלי האינדקס.
    """
    from sticky_notes_target import active_notes_filter, archived_notes_filter

    _seed(db, USER, archived=300, active=1000)
    _seed(db, OTHER, archived=50, active=50)

    for name, query, expected in (("active", active_notes_filter(USER), 1000),
                                  ("archived", archived_notes_filter(USER), 300)):
        assert db.sticky_notes.count_documents(query) == expected, name
        explain = db.command(
            "explain",
            {"aggregate": "sticky_notes", "cursor": {},
             "pipeline": [{"$match": query}, {"$group": {"_id": 1, "n": {"$sum": 1}}}]},
            verbosity="executionStats", codec_options=_EXPLAIN_CODEC,
        )
        stages, stats = _plan_stages(explain)
        assert "COUNT_SCAN:user_archived_idx" in stages, (name, stages)
        assert stats["totalDocsExamined"] == 0, (name, stats["totalDocsExamined"])


def test_the_list_the_route_sends_is_read_in_index_order_without_a_sort(api, db):
    """**השאילתה שהראוט שולח**, כפי שנרשמה בדרך — לא עותק שלה. בלי שלב ``SORT`` (המיון הוא סדר
    האינדקס), וכל מסמך שנקרא הוא כרטיס שחוזר. והתשובה: מהחדש לישן, בלי גוף הפתק."""
    _seed(db, USER, archived=300, active=1000)

    res = api.client().get("/api/sticky-notes/archive")
    body = res.get_json()

    assert res.status_code == 200 and body["count"] == 300
    stamps = [card["archived_at"] for card in body["notes"]]
    assert stamps == sorted(stamps, reverse=True), "מהחדש לישן"
    assert all("content" not in card for card in body["notes"])

    [sent] = [f for f in api.recording.finds if f["sort"] is not None]
    explain = db.command(
        "explain",
        {"find": "sticky_notes", "filter": sent["filter"], "projection": sent["projection"],
         "sort": dict(sent["sort"])},
        verbosity="executionStats", codec_options=_EXPLAIN_CODEC,
    )
    stages, stats = _plan_stages(explain)
    assert not any(s.startswith("SORT") for s in stages), stages
    assert "IXSCAN:user_archived_idx" in stages, stages
    assert stats["totalDocsExamined"] == stats["nReturned"] == 300


# == ההעברה מקצה לקצה ========================================================================


def test_archiving_moves_the_note_resolves_its_open_threads_and_keeps_its_reminder(api, db):
    """הכול נקרא חזרה מהמסד: השדות של היעד הקודם נמחקו, השם נשמר, השרשור הפתוח נסגר והסגור לא
    נגע, והתזכורת — כמו שהייתה."""
    board = insert_board(db, USER)
    note = insert_note(db, USER, board_id=board, content="# רעיון\nגוף", mode="surface",
                       line_start=3, anchor_text="x")
    threads = db[nt.NOTE_THREADS_COLLECTION]
    open_tid = nt.create_thread(threads, user_id=USER, note_id=note, author=nt.user_author(), body="?")["thread_id"]
    closed_tid = nt.create_thread(threads, user_id=USER, note_id=note, author=nt.user_author(), body="!")["thread_id"]
    nt.resolve_thread(threads, user_id=USER, note_id=note, thread_id=closed_tid, author=nt.user_author())
    closed_before = threads.find_one({"_id": ObjectId(closed_tid)})
    client = api.client()
    assert client.post(f"/api/sticky-notes/note/{note}/reminder", json={"preset": "24h"}).status_code == 200
    reminder_before = db.note_reminders.find_one({"note_id": note}, {"_id": 0})

    res = _archive(client, note, title="רעיון")
    body = res.get_json()

    assert res.status_code == 200 and body["ok"] is True and body["threads_resolved"] == 1, body
    stored = db.sticky_notes.find_one({"_id": ObjectId(note)})
    assert isinstance(stored["archived_at"], datetime) and stored["archived_at"].tzinfo is not None
    assert stored["title"] == "רעיון"
    for gone in ("board_id", "mode", "line_start", "anchor_text", "file_id", "repo_name"):
        assert gone not in stored, gone
    assert body["note"]["archived_at"], "התשובה נבנתה מהמסמך שנכתב"

    opened = threads.find_one({"_id": ObjectId(open_tid)})
    assert opened["status"] == nt.STATUS_RESOLVED
    assert opened["resolved_by"]["kind"] == "user"
    assert threads.find_one({"_id": ObjectId(closed_tid)}) == closed_before, "שרשור סגור לא נגע"
    assert db.note_reminders.find_one({"note_id": note}, {"_id": 0}) == reminder_before


def test_the_title_the_note_held_on_its_board_is_free_after_archiving(api, db):
    """"ארכיון הוא יעד חדש". הבקרה קודם: לפני ההעברה אותו שם נדחה — אחרת "נוצר" היה נכון גם
    בלי אינדקס השם כלל."""
    board = insert_board(db, USER)
    note = insert_note(db, USER, board_id=board, title="שם")
    client = api.client()

    before = client.post(f"/api/sticky-notes/board/{board}", json={"content": "שני", "title": "שם"})
    assert before.status_code == 409 and before.get_json()["error"] == "duplicate_title"

    assert _archive(client, note).get_json()["ok"] is True
    after = client.post(f"/api/sticky-notes/board/{board}", json={"content": "שני", "title": "שם"})

    assert after.status_code in (200, 201), after.get_json()
    assert db.sticky_notes.count_documents({"user_id": USER, "title": "שם"}) == 2


def test_two_concurrent_archives_of_one_note_write_once(api, db, monkeypatch):
    """שתי בקשות עוברות את הקריאה, ורק אז מותר להן לכתוב (``Barrier`` בין הקריאה לכתיבה).
    אחת כותבת וסוגרת את השרשורים; השנייה עונה ``already_archived`` בלי לכתוב."""
    board = insert_board(db, USER)
    note = insert_note(db, USER, board_id=board, title="שם")
    nt.create_thread(db[nt.NOTE_THREADS_COLLECTION], user_id=USER, note_id=note, author=nt.user_author(), body="?")
    gate = threading.Barrier(2, timeout=10)
    real_resolve = api.module.resolve_archive_title

    def after_both_read(*args, **kwargs):
        gate.wait()
        return real_resolve(*args, **kwargs)

    monkeypatch.setattr(api.module, "resolve_archive_title", after_both_read)
    answers: list[dict] = []

    def go() -> None:
        answers.append(_archive(api.client(), note).get_json())

    workers = [threading.Thread(target=go) for _ in range(2)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(20)

    assert len(answers) == 2 and all(a["ok"] is True for a in answers), answers
    assert sorted(a["already_archived"] for a in answers) == [False, True]
    [winner] = [a for a in answers if a["already_archived"] is False]
    assert winner["threads_resolved"] == 1
    stored = db.sticky_notes.find_one({"_id": ObjectId(note)})
    assert stored["archived_at"].isoformat() == datetime.fromisoformat(winner["note"]["archived_at"]).isoformat()


# == תקרת 1000: כל הכותבים מחריגים את הארכיון ===============================================


def _writer(name: str, api, db, monkeypatch, marker: str) -> None:
    """כותב אחד מבין השישה שסופרים את תקרת המשתמש, דרך הממשק שלו."""
    import user_roles

    monkeypatch.setattr(user_roles, "is_admin", lambda uid: False)
    board = insert_board(db, USER, "CodeBot")
    db.repo_metadata.insert_one({"repo_name": "CodeBot"})
    db.repo_files.insert_one({"repo_name": "CodeBot", "path": "a.py"})
    client = api.client()
    if name == "webapp_file":
        file_id = insert_file(db, USER, "x.md")
        client.post(f"/api/sticky-notes/{file_id}", json={"content": marker})
    elif name == "webapp_board":
        client.post(f"/api/sticky-notes/board/{board}", json={"content": marker})
    elif name == "webapp_repo":
        client.post("/api/sticky-notes/repo/CodeBot/a.py", json={"content": marker})
    elif name in ("mcp_board", "mcp_repo"):
        from mcp_server.backend import ProductionBackend

        backend = ProductionBackend(mongo_db=db)
        if name == "mcp_board":
            backend.create_board_note(USER, board_id=board, content=marker, color="#FFFFCC", mode="surface")
        else:
            backend.create_repo_note(USER, repo_name="CodeBot", repo_path="a.py", content=marker,
                                     color="#FFFFCC", mode="surface")
    elif name == "backup_board":
        from services.personal_backup_service import PersonalBackupService

        PersonalBackupService(SimpleNamespace(db=db))._restore_sticky_notes(
            USER, [{"board_name": "CodeBot", "content": marker}], [])
    else:  # pragma: no cover - רשימת הפרמטרים למטה היא הרשימה
        raise AssertionError(name)


_WRITERS = ("webapp_file", "webapp_board", "webapp_repo", "mcp_board", "mcp_repo", "backup_board")


@pytest.mark.parametrize("writer", _WRITERS)
def test_archived_notes_do_not_fill_the_per_user_cap(writer, api, db, monkeypatch):
    """1000 פתקים בארכיון ואפס פעילים — הכותב יוצר פתק. נבדק בקריאה מהמסד, לא בתשובה."""
    from sticky_notes_target import MAX_NOTES_PER_USER

    _seed(db, USER, archived=MAX_NOTES_PER_USER)
    marker = f"חדש-{writer}"

    _writer(writer, api, db, monkeypatch, marker)

    assert db.sticky_notes.count_documents({"user_id": USER, "content": marker}) == 1


@pytest.mark.parametrize("writer", _WRITERS)
def test_active_notes_still_fill_the_per_user_cap(writer, api, db, monkeypatch):
    """הבקרה: 1000 פתקים **פעילים** (על לוח אחר, כדי שרק התקרה למשתמש תכריע) — נדחה. בלעדיה
    הבדיקה שמעל הייתה עוברת גם לכותב שאינו סופר כלום."""
    from sticky_notes_target import MAX_NOTES_PER_USER

    _seed(db, USER, active=MAX_NOTES_PER_USER)
    marker = f"חדש-{writer}"

    _writer(writer, api, db, monkeypatch, marker)

    assert db.sticky_notes.count_documents({"user_id": USER, "content": marker}) == 0


# == גיבוי ושחזור ===========================================================================


def test_an_archived_note_survives_backup_and_restore_with_its_title_and_place(api, db):
    """ייצוא, JSON (כמו בקובץ ה-ZIP), שחזור למשתמש אחר: הפתק בארכיון, עם השם והזמן שלו. שחזור
    שני אינו מכפיל."""
    from services.personal_backup_service import PersonalBackupService
    from sticky_notes_target import active_notes_filter, archived_notes_filter, note_target_kind

    note = insert_note(db, USER, board_id=insert_board(db, USER), title="שם", content="גוף")
    assert _archive(api.client(), note).get_json()["ok"] is True
    original = db.sticky_notes.find_one({"_id": ObjectId(note)})
    service = PersonalBackupService(SimpleNamespace(db=db))
    exported = json.loads(json.dumps(service._export_sticky_notes(USER), ensure_ascii=False))

    errors: list[str] = []
    assert service._restore_sticky_notes(OTHER, exported, errors) == 1, errors
    restored = db.sticky_notes.find_one(archived_notes_filter(OTHER))
    assert note_target_kind(restored) == "archive"
    assert restored["title"] == "שם" and restored["content"] == "גוף"
    assert abs(restored["archived_at"] - original["archived_at"]) < timedelta(milliseconds=2)
    assert db.sticky_notes.count_documents(active_notes_filter(OTHER)) == 0

    assert service._restore_sticky_notes(OTHER, exported, []) == 0
    assert db.sticky_notes.count_documents(archived_notes_filter(OTHER)) == 1


def test_restore_refuses_archived_notes_beyond_the_archive_cap_and_says_so(db):
    from services.personal_backup_service import PersonalBackupService
    from sticky_notes_target import MAX_ARCHIVED_NOTES_PER_USER, archived_notes_filter

    _seed(db, OTHER, archived=MAX_ARCHIVED_NOTES_PER_USER)
    errors: list[str] = []
    written = PersonalBackupService(SimpleNamespace(db=db))._restore_sticky_notes(
        OTHER, [{"content": "עוד", "title": "שם", "archived_at": "2026-10-25T09:00:00+00:00"}], errors)

    assert written == 0 and len(errors) == 1, errors
    assert db.sticky_notes.count_documents(archived_notes_filter(OTHER)) == MAX_ARCHIVED_NOTES_PER_USER


# == MCP ושורת הפריימר ======================================================================


def test_the_mcp_sees_an_archived_note_where_it_is(api, db, monkeypatch):
    """אחרי ההעברה: ``get_note`` אומר ``archive``, הפתק אינו ברשימת הלוח שהיה עליו, ותגובה חדשה
    של המשתמש עליו מופיעה בפריימר "בארכיון" — דרך ``pending_note_threads`` האמיתי."""
    from starlette.applications import Starlette
    from starlette.testclient import TestClient

    from mcp_server import primer
    from mcp_server.backend import ProductionBackend

    board = insert_board(db, USER)
    note = insert_note(db, USER, board_id=board, title="רעיון")
    assert _archive(api.client(), note).get_json()["ok"] is True
    backend = ProductionBackend(mongo_db=db)

    assert backend.get_note(USER, note_id=note)["target"] == "archive"
    assert backend.list_board_notes(USER, board_id=board)["count"] == 0

    nt.create_thread(db[nt.NOTE_THREADS_COLLECTION], user_id=USER, note_id=note,
                     author=nt.user_author(), body="עוד משהו")
    db.user_preferences.insert_one({"user_id": USER, "agent_instructions": "כללים"})
    monkeypatch.setattr(primer, "is_admin_user", lambda uid: False)

    class _Store:
        def verify(self, token):
            return {"user_id": USER, "scopes": ["read"]} if token == "good" else None

    app = Starlette(routes=[primer.agent_primer_route(backend, token_store=_Store(), cache=primer.PrimerCache())])
    text = TestClient(app).get("/api/agent/primer", headers={"Authorization": "Bearer good"}).text

    assert f'"רעיון" בארכיון (note_id {note})' in text



# == החיפוש: הארכיון בחוץ, אלא אם ביקשו ======================================================


def test_both_searches_leave_the_archive_out_unless_asked(api, db):
    """אותה תשובה בוובאפ וב-MCP, כי ההסתרה בפילטר המשותף. פתק שהועבר בבקשה האמיתית — לא מסמך
    שנכתב ביד בצורה שאולי אינה הצורה של ההעברה."""
    from mcp_server.backend import ProductionBackend

    board = insert_board(db, USER)
    live = insert_note(db, USER, board_id=board, title="רעיון פעיל")
    gone = insert_note(db, USER, board_id=board, title="רעיון ישן")
    assert _archive(api.client(), gone).get_json()["ok"] is True
    backend = ProductionBackend(mongo_db=db)
    web = api.client()

    hidden = backend.search_notes(USER, query="רעיון", limit=20)
    assert [n["id"] for n in hidden["notes"]] == [live] and hidden["searched_archive"] is False
    hidden = web.get("/api/sticky-notes/search?q=רעיון").get_json()
    assert [h["id"] for h in hidden["results"]] == [live] and hidden["include_archived"] is False

    both = {live: "board", gone: "archive"}
    shown = backend.search_notes(USER, query="רעיון", limit=20, include_archived=True)
    assert {n["id"]: n["target"] for n in shown["notes"]} == both and shown["searched_archive"] is True
    shown = web.get("/api/sticky-notes/search?q=רעיון&include_archived=1").get_json()
    assert {h["id"]: h["target"] for h in shown["results"]} == both


def _seed_words(db) -> None:
    """לכל אחד משני משתמשים: 1000 פתקים פעילים — מילה נדירה באחד מכל חמישים, מילה נפוצה בשאר —
    ו-300 בארכיון. אותה צורה שבה נמדד מטמון התוכניות לפני שהאינדקס נוסף."""
    now = datetime.now(timezone.utc)
    docs = []
    for user in (USER, OTHER):
        docs += [{"user_id": user, "board_id": "b", "updated_at": now - timedelta(minutes=i),
                  "content": ("מילה נדירה " if i % 50 == 0 else "תוכן רגיל ") * 20} for i in range(1000)]
        docs += [{"user_id": user, "content": "ארכיון " * 20, "archived_at": now - timedelta(seconds=i),
                  "updated_at": now - timedelta(minutes=2000 + i)} for i in range(300)]
    db.sticky_notes.insert_many(docs)


def test_a_common_word_after_a_rare_one_still_reads_in_order_and_stops_at_the_cap(api, db):
    """**מטמון התוכניות.** מונגו שומרת את התוכנית שניצחה ומריצה אותה שוב לשאילתה באותה צורה. לפני
    ``user_archived_updated_idx``, מילה נדירה ניצחה עם ``user_archived_idx`` ו-``SORT``, ומילה נפוצה
    שבאה אחריה רצה על אותה תוכנית וקראה את כל אלף הפתקים הפעילים — בכל פעם (נמדד בפרופיילר).
    האינדקס נותן את השוויון ואת סדר המיון יחד, ולכן גם מתוך המטמון הקריאה נעצרת בתקרה.

    רץ על ``search_notes`` האמיתי של ה-MCP — ``find`` עם מיון ב-``updated_at`` ותקרה — ונמדד
    בפרופיילר של המסד הזמני, על השאילתות שבאמת רצו. נופל על מסד בלי האינדקס."""
    from mcp_server.backend import ProductionBackend

    _seed_words(db)
    backend = ProductionBackend(mongo_db=db)
    backend.search_notes(USER, query="חימום", limit=20)  # בונה את האינדקסים לפני המדידה

    db.command("profile", 2)
    try:
        for word in ("נדירה", "נדירה", "תוכן", "תוכן"):
            out = backend.search_notes(USER, query=word, limit=20, search_content=True, content_query=word)
            assert out["ok"] is True and out["count"] == 20
        runs = list(db.system.profile.find(
            {"op": "query", "ns": f"{db.name}.sticky_notes"},
            {"planSummary": 1, "docsExamined": 1},
        ).sort("ts", 1))
    finally:
        db.command("profile", 0)

    assert len(runs) == 4, runs
    for run in runs[2:]:
        assert run["docsExamined"] <= 50, run  # 21 נדרשים (תקרה ושורת סנטינל); בלי האינדקס — 1000
    # הפרופיילר מסכם תוכנית לפי מפתחות האינדקס ולא לפי שמו — ולכן התבנית נגזרת מהמפרט.
    keys = dict(api.module._QUERY_INDEX_SPECS)["user_archived_updated_idx"]
    expected_scan = "IXSCAN { " + ", ".join(f"{field}: {order}" for field, order in keys) + " }"
    assert all(run["planSummary"] == expected_scan for run in runs[2:]), runs


def _values_of(node: Any, key: str) -> list:
    if isinstance(node, dict):
        return [v for k, v in node.items() if k == key] + [x for v in node.values() for x in _values_of(v, key)]
    if isinstance(node, list):
        return [x for v in node for x in _values_of(v, key)]
    return []


def test_the_search_sorts_what_it_returns_and_not_the_note_bodies(api, db):
    """``mongodb.md`` דפוס 5: ``$project`` בהחרגה אחרי ``$addFields`` לא הוריד את הגוף מהמיון.
    נמדד על **הצינור שהראוט שלח**: ``totalDataSizeSortedBytesEstimate`` של 1,792,484 בייטים על
    200 פתקים ארוכים בעברית בתקרה של 50 — כלומר 51 גופים שלמים — מול 57,260 בהכללה.

    הגבול כאן הוא שלושה גופים: הקלט של המיון אינו אמור לגדול עם הגוף בכלל, ו-51 גופים חוצים אותו
    בפער גדול. נופל על ``{"content": 0}``."""
    note_body = ("מילה " * 4000)[:19000]
    now = datetime.now(timezone.utc)
    db.sticky_notes.insert_many([
        {"user_id": USER, "board_id": "b", "title": f"כותרת {i}", "content": note_body,
         "updated_at": now - timedelta(minutes=i)}
        for i in range(200)
    ])

    res = api.client().get("/api/sticky-notes/search?q=מילה&limit=50").get_json()
    assert res["ok"] is True and res["count"] == 50 and res["truncated"] is True

    [pipeline] = api.recording.aggregates
    explain = db.command(
        "explain", {"aggregate": "sticky_notes", "pipeline": pipeline, "cursor": {}},
        verbosity="executionStats", codec_options=_EXPLAIN_CODEC,
    )
    sorted_bytes = _values_of(explain, "totalDataSizeSortedBytesEstimate")
    assert sorted_bytes, "אין שלב מיון בתוכנית — הבדיקה אינה מודדת דבר"
    assert max(sorted_bytes) < 3 * len(note_body.encode("utf-8")), sorted_bytes
