"""``note_threads`` מול **מונגו אמיתי** — מה שסטאב אינו יכול לבדוק.

האטומיות, התקרות שבפילטר תחת כתיבות מקבילות, הבידוד בין משתמשים, ``$slice`` במסד,
ובחירת האינדקס — כולם התנהגות של המסד ולא של הקוד. סטאב שמחזיר את מה שכתבנו אליו היה
מאשר כל אחד מהם גם כשהוא שבור.

מתי הן רצות: כש-``MONGODB_URL`` מוגדר והשרת נענה — אותו כלל של
``tests/test_note_boards_mongo.py`` (ראו שם למה ב-CI של ה-PR הן מדלגות ואחרי מיזוג רצות).
**מדלגים רק על "אין שרת"** (``ServerSelectionTimeoutError``, ``ConnectionFailure``): שגיאת
תצורה או אימות היא כשל, לא דילוג.

**בטיחות מחיקה:** כל טסט עובד על מסד עם שם ייחודי בתחילית ``codebot_threads_it_``, וה-
teardown מוחק רק מסד שמתחיל בה.
"""

from __future__ import annotations

import ast
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytest.importorskip("pymongo")

from bson import ObjectId  # noqa: E402

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _note_threads_harness import mongo_reachable, temp_database  # noqa: E402

import note_threads as nt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
USER, OTHER = 7, 99

pytestmark = pytest.mark.skipif(not mongo_reachable(), reason="דורש MONGODB_URL עם שרת מונגו נגיש")


@pytest.fixture
def db():
    """מסד חד-פעמי, ``tz_aware=True`` כמו בייצור (``database/manager.py``)."""
    with temp_database("codebot_threads_it_") as database:
        yield database


@pytest.fixture
def coll(db):
    return db[nt.NOTE_THREADS_COLLECTION]


def _note() -> str:
    return str(ObjectId())


def _agent(working_on: str = "אפיון שרשורי תגובות", client: str = "claude-code") -> dict:
    return nt.agent_author(client=client, working_on=working_on)


def _create(coll, note_id: str, *, user_id: int = USER, author=None, body: str = "פתיחה") -> str:
    res = nt.create_thread(coll, user_id=user_id, note_id=note_id, author=author or _agent(), body=body)
    assert res["ok"] is True, res
    return res["thread_id"]


def _doc(coll, thread_id: str) -> dict:
    return coll.find_one({"_id": ObjectId(thread_id)})


# -- יצירה ------------------------------------------------------------------------


def test_a_new_thread_is_stored_open_with_its_first_comment_and_read_back(coll):
    note = _note()
    res = nt.create_thread(coll, user_id=USER, note_id=note, author=_agent(), body="גוף  \r\n&amp;")

    assert res["ok"] is True and res["action"] == "created"
    stored = _doc(coll, res["thread_id"])
    # התשובה היא הקריאה החוזרת — אותו מסמך שבמסד.
    assert res["thread"] == stored
    assert stored["user_id"] == USER and stored["note_id"] == note
    assert stored["status"] == "open" and stored["resolved_by"] is None and stored["resolved_at"] is None
    assert stored["last_author_kind"] == "agent"
    assert stored["comment_count"] == 1
    assert stored["body_bytes"] == nt.body_wire_bytes("גוף  \r\n&amp;")
    (comment,) = stored["comments"]
    assert comment["body"] == "גוף  \r\n&amp;"  # בדיוק כפי שנשלח
    assert comment["author"] == {"kind": "agent", "client": "claude-code", "working_on": "אפיון שרשורי תגובות"}
    assert comment["id"] == res["comment_id"]
    assert stored["created_at"] == stored["last_at"] == comment["created_at"]
    assert stored["created_at"].tzinfo is not None
    assert nt.stored_comment(res) == comment


def test_an_invalid_body_writes_nothing(coll):
    note = _note()
    for body in ("", "  \n", "x" * (nt.MAX_COMMENT_CHARS + 1), None):
        res = nt.create_thread(coll, user_id=USER, note_id=note, author=_agent(), body=body)
        assert res["ok"] is False, body
    assert coll.count_documents({}) == 0


# -- תשובה, פתיחה מחדש, סגירה ------------------------------------------------------------


def test_answering_a_resolved_thread_reopens_it_and_records_the_author_in_one_write(coll):
    """**האטומיות של הפתיחה מחדש — נבדקת במבנה, לא בהסתברות.**

    האפיון: "תגובה חדשה היא ``$push`` אחד שמעדכן באותה פעולה אטומית גם את
    ``last_author_kind``, את ``last_at`` ואת הסטטוס". מרוץ שהיה חושף מצב ביניים אינו
    משתחזר בוודאות, ולכן הטסט עוטף את האוסף האמיתי ורושם **כל כתיבה**: התשובה חייבת להיות
    כתיבה אחת שנושאת את התגובה, את הכותב האחרון ואת הסטטוס יחד. מימוש בשתי כתיבות (דחיפה
    ואחריה עדכון סטטוס) נופל כאן — זו המוטציה שהטסט נבנה עליה.
    """
    note = _note()
    tid = _create(coll, note, author=_agent())
    assert nt.resolve_thread(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent())["ok"]

    writes = []

    class _Recording:
        def __init__(self, inner):
            self._inner = inner

        def __getattr__(self, name):
            attr = getattr(self._inner, name)
            if name in ("update_one", "update_many", "find_one_and_update", "replace_one",
                        "insert_one", "find_one_and_replace", "bulk_write"):
                def recorded(*args, **kwargs):
                    writes.append((name, args, kwargs))
                    return attr(*args, **kwargs)
                return recorded
            return attr

    res = nt.add_comment(_Recording(coll), user_id=USER, note_id=note, thread_id=tid,
                         author=nt.user_author(), body="עדיין לא עובד")

    assert res["ok"] is True and res["action"] == "replied"
    assert [w[0] for w in writes] == ["find_one_and_update"]
    update = writes[0][1][1]
    assert update["$push"]["comments"]["body"] == "עדיין לא עובד"
    assert update["$set"]["status"] == "open"
    assert update["$set"]["resolved_by"] is None and update["$set"]["resolved_at"] is None
    assert update["$set"]["last_author_kind"] == "user"
    stored = _doc(coll, tid)
    assert (stored["status"], stored["last_author_kind"], stored["resolved_by"]) == ("open", "user", None)
    assert stored["last_at"] == stored["comments"][-1]["created_at"]


def test_answering_without_reopening_keeps_it_resolved_but_moves_the_last_author(coll):
    note = _note()
    tid = _create(coll, note)
    nt.resolve_thread(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent(), body="סיכום")
    before = _doc(coll, tid)

    res = nt.add_comment(coll, user_id=USER, note_id=note, thread_id=tid, author=nt.user_author(),
                         body="תודה", reopen=False)

    stored = _doc(coll, tid)
    assert res["ok"] is True
    assert stored["status"] == "resolved" and stored["resolved_by"] == before["resolved_by"]
    assert stored["last_author_kind"] == "user" and stored["comment_count"] == 3


def test_resolving_records_who_and_when_and_a_summary_in_the_same_write(coll):
    note = _note()
    tid = _create(coll, note)
    who = _agent(working_on="סגירת שרשור", client="Gemini")

    res = nt.resolve_thread(coll, user_id=USER, note_id=note, thread_id=tid, author=who, body="נפתר ב-PR 28")

    stored = _doc(coll, tid)
    assert res["ok"] is True and res["action"] == "resolved"
    assert stored["status"] == "resolved"
    assert stored["resolved_by"] == {"kind": "agent", "client": "Gemini", "working_on": "סגירת שרשור"}
    assert stored["resolved_at"] == stored["last_at"] == stored["comments"][-1]["created_at"]
    assert stored["comments"][-1]["body"] == "נפתר ב-PR 28" and stored["comment_count"] == 2
    assert nt.stored_comment(res)["body"] == "נפתר ב-PR 28"


def test_resolving_a_resolved_thread_writes_nothing_not_even_the_summary(coll):
    note = _note()
    tid = _create(coll, note)
    nt.resolve_thread(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent())
    before = _doc(coll, tid)

    res = nt.resolve_thread(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent(), body="שוב")

    assert res == {"ok": False, "error": "already_resolved"}
    assert _doc(coll, tid) == before


def test_resolving_without_a_summary_leaves_the_last_author_alone(coll):
    note = _note()
    tid = _create(coll, note, author=nt.user_author())

    nt.resolve_thread(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent())

    stored = _doc(coll, tid)
    assert stored["last_author_kind"] == "user" and stored["comment_count"] == 1


def test_reopen_only_opens_a_resolved_thread_and_adds_no_comment(coll):
    note = _note()
    tid = _create(coll, note)
    assert nt.reopen_thread(coll, user_id=USER, note_id=note, thread_id=tid) == {"ok": False, "error": "not_resolved"}
    nt.resolve_thread(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent())

    res = nt.reopen_thread(coll, user_id=USER, note_id=note, thread_id=tid)

    stored = _doc(coll, tid)
    assert res["ok"] is True and res["action"] == "reopened"
    assert (stored["status"], stored["resolved_by"], stored["resolved_at"]) == ("open", None, None)
    assert stored["comment_count"] == 1


# -- תקרות -------------------------------------------------------------------------


def test_a_full_thread_refuses_and_writes_nothing(coll):
    note = _note()
    tid = _create(coll, note)
    for i in range(nt.MAX_COMMENTS_PER_THREAD - 1):
        assert nt.add_comment(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent(), body=f"#{i}")["ok"]
    before = _doc(coll, tid)

    res = nt.add_comment(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent(), body="עוד אחת")

    assert res == {"ok": False, "error": "thread_full", "max": nt.MAX_COMMENTS_PER_THREAD}
    assert _doc(coll, tid) == before and len(before["comments"]) == nt.MAX_COMMENTS_PER_THREAD
    # וגם סגירה עם סיכום — היא תגובה, ולכן בתקרה; סגירה בלי סיכום עדיין אפשרית.
    assert nt.resolve_thread(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent(),
                             body="סיכום")["error"] == "thread_full"
    assert nt.resolve_thread(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent())["ok"] is True


def test_a_thread_past_its_byte_budget_refuses_and_writes_nothing(coll):
    note = _note()
    big = "\x01" * nt.MAX_COMMENT_CHARS  # שישה בתים לתו ב-JSON
    tid = _create(coll, note, body=big)
    while True:
        res = nt.add_comment(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent(), body=big)
        if not res["ok"]:
            break
    stored = _doc(coll, tid)
    assert res == {"ok": False, "error": "thread_too_long", "max_bytes": nt.MAX_THREAD_BODY_BYTES}
    assert stored["body_bytes"] == sum(nt.body_wire_bytes(c["body"]) for c in stored["comments"])
    assert stored["body_bytes"] + nt.body_wire_bytes(big) > nt.MAX_THREAD_BODY_BYTES >= stored["body_bytes"]


def test_concurrent_answers_cannot_pass_the_comment_cap_together(coll):
    """**במקביל, לא ברצף** (testing.md §3): 60 תשובות מקבילות לשרשור עם תגובה אחת.

    התקרה יושבת בפילטר, ולכן בדיוק ``MAX - 1`` מצליחות והשאר עונות ``thread_full`` —
    ומה שבמסד עקבי: המונה שווה למספר התגובות. בדיקה-ואז-כתיבה בקוד הייתה עוברת את התקרה.
    """
    note = _note()
    tid = _create(coll, note)
    barrier = threading.Barrier(60)

    def answer(i: int) -> dict:
        barrier.wait()
        return nt.add_comment(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent(), body=f"#{i}")

    with ThreadPoolExecutor(max_workers=60) as pool:
        results = list(pool.map(answer, range(60)))

    stored = _doc(coll, tid)
    assert sum(r["ok"] for r in results) == nt.MAX_COMMENTS_PER_THREAD - 1
    assert {r.get("error") for r in results if not r["ok"]} == {"thread_full"}
    assert stored["comment_count"] == len(stored["comments"]) == nt.MAX_COMMENTS_PER_THREAD
    assert stored["body_bytes"] == sum(nt.body_wire_bytes(c["body"]) for c in stored["comments"])


def test_concurrent_resolve_and_answer_never_leave_a_half_state(coll):
    """סגירה ותשובה מקבילות, שוב ושוב: בכל רגע ``status`` ו-``resolved_by`` מסכימים."""
    note = _note()
    tid = _create(coll, note)
    for _round in range(15):
        barrier = threading.Barrier(2)

        def resolve():
            barrier.wait()
            return nt.resolve_thread(coll, user_id=USER, note_id=note, thread_id=tid, author=_agent())

        def answer():
            barrier.wait()
            return nt.add_comment(coll, user_id=USER, note_id=note, thread_id=tid, author=nt.user_author(), body="?")

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(resolve), pool.submit(answer)]
            for f in futures:
                f.result()
        stored = _doc(coll, tid)
        assert (stored["status"] == "open") == (stored["resolved_by"] is None) == (stored["resolved_at"] is None)


# -- תחום: משתמש ופתק --------------------------------------------------------------------


def test_a_thread_of_another_user_or_another_note_is_not_found_and_untouched(coll):
    """``thread_id`` של משתמש אחר — גם כשהקורא נוקב ב-``note_id`` הנכון — ושל פתק אחר של
    אותו משתמש: "לא נמצא", ושום דבר לא נכתב. התחום בפילטר, לא בבדיקה אחריו."""
    note, other_note = _note(), _note()
    foreign = _create(coll, note, user_id=OTHER)
    mine_elsewhere = _create(coll, other_note)
    before = list(coll.find({}).sort("_id", 1))

    for tid, note_id in ((foreign, note), (mine_elsewhere, note)):
        for res in (
            nt.add_comment(coll, user_id=USER, note_id=note_id, thread_id=tid, author=_agent(), body="x"),
            nt.resolve_thread(coll, user_id=USER, note_id=note_id, thread_id=tid, author=_agent(), body="x"),
            nt.reopen_thread(coll, user_id=USER, note_id=note_id, thread_id=tid),
        ):
            assert res == {"ok": False, "error": "thread_not_found"}, (tid, res)
    assert list(coll.find({}).sort("_id", 1)) == before


def test_reads_never_cross_users(coll):
    note = _note()
    _create(coll, note, user_id=OTHER, author=nt.user_author())
    mine = _create(coll, note)

    assert [str(t["_id"]) for t in nt.list_threads(coll, user_id=USER, note_id=note)] == [mine]
    assert nt.open_thread_counts(coll, user_id=USER, note_ids=[note]) == {note: 1}
    assert nt.pending_for_agent(coll, user_id=USER) == []  # של OTHER ממתין, לא של USER
    assert nt.delete_note_threads(coll, user_id=USER, note_id=note) == 1
    assert coll.count_documents({"user_id": OTHER}) == 1


# -- קריאה ---------------------------------------------------------------------------------


def test_threads_are_numbered_by_creation_and_comments_tail_in_the_database(coll):
    note = _note()
    first = _create(coll, note, body="1")
    second = _create(coll, note, body="2")
    for i in range(14):
        nt.add_comment(coll, user_id=USER, note_id=note, thread_id=first, author=_agent(), body=f"c{i}")

    listed = nt.list_threads(coll, user_id=USER, note_id=note)
    assert [(str(t["_id"]), t["number"]) for t in listed] == [(first, 1), (second, 2)]
    assert all("comments" not in t for t in listed)

    tails = nt.load_comments(coll, user_id=USER, note_id=note, thread_ids=[first, second], tail=3)
    assert [c["body"] for c in tails[first]] == ["c11", "c12", "c13"]
    assert [c["body"] for c in tails[second]] == ["2"]
    full = nt.load_comments(coll, user_id=USER, note_id=note, thread_ids=[first], tail=None)
    assert len(full[first]) == 15


def test_pending_is_open_threads_whose_last_comment_is_the_users_newest_first(coll):
    a, b, c, d = _note(), _note(), _note(), _note()
    _create(coll, a, author=nt.user_author())                       # ממתין
    t_b = _create(coll, b, author=nt.user_author())                 # הסוכן ענה — לא ממתין
    nt.add_comment(coll, user_id=USER, note_id=b, thread_id=t_b, author=_agent(), body="טופל")
    t_c = _create(coll, c, author=_agent())                         # המשתמש ענה — ממתין
    nt.add_comment(coll, user_id=USER, note_id=c, thread_id=t_c, author=nt.user_author(), body="?")
    t_d = _create(coll, d, author=nt.user_author())                 # נפתר — לא ממתין
    nt.resolve_thread(coll, user_id=USER, note_id=d, thread_id=t_d, author=nt.user_author())

    assert [p["note_id"] for p in nt.pending_for_agent(coll, user_id=USER)] == [c, a]


# -- אינדקסים ------------------------------------------------------------------------------


class _Dbm:
    """``DatabaseManager`` מינימלי מעל מסד הבדיקה — ``safe_create_index`` האמיתי."""

    def __init__(self, db):
        self.db = db

    def safe_create_index(self, *args, **kwargs):
        from database.manager import DatabaseManager

        return DatabaseManager.safe_create_index(self, *args, **kwargs)


def test_the_declared_indexes_exist_and_the_queries_use_them(db, coll):
    """ההצהרה האמיתית (``DatabaseManager._create_note_threads_indexes``) מול ``mongod``, ו-
    ``explain`` על שתי השאילתות שהאינדקסים נועדו להן: לא ``COLLSCAN``."""
    from database.manager import DatabaseManager

    dbm = _Dbm(db)
    results = DatabaseManager._create_note_threads_indexes(dbm, dbm.safe_create_index)
    assert results == {nt.NOTE_THREADS_BY_NOTE_INDEX: True, nt.NOTE_THREADS_PENDING_INDEX: True}
    names = {ix["name"] for ix in coll.list_indexes()}
    assert {nt.NOTE_THREADS_BY_NOTE_INDEX, nt.NOTE_THREADS_PENDING_INDEX} <= names

    note = _note()
    _create(coll, note)

    def winning_index(cursor) -> str:
        plan = cursor.explain()["queryPlanner"]["winningPlan"]
        text = str(plan)
        assert "COLLSCAN" not in text, plan
        return text

    by_note = winning_index(coll.find(nt.thread_scope(USER, note), {"comments": 0}))
    assert nt.NOTE_THREADS_BY_NOTE_INDEX in by_note
    pending = winning_index(coll.find({"user_id": USER, "status": "open", "last_author_kind": "user"}))
    assert nt.NOTE_THREADS_PENDING_INDEX in pending


def test_every_service_declares_the_indexes_at_startup():
    """``_create_indexes`` — המסלול ששני השירותים עוברים בעלייה — קורא להצהרה.

    נבדק ב-AST ולא בהרצה: ``_create_indexes`` בונה עשרות אינדקסים על אוספים אחרים.
    """
    source = (ROOT / "database" / "manager.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    create = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "_create_indexes")
    called = {node.func.attr for node in ast.walk(create)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert "_create_note_threads_indexes" in called
