"""בדיקות החיבור של הצ'קליסט "צעדים ראשונים" מול mongod אמיתי — מה שדמה לא יכולה להראות.

**כמה השרת קורא.** "יש חיבור חי?" צריכה מסמך אחד מהשרת. דמה מחזירה את אותה תשובה גם כשהשרת
עובר על כל השורות של המשתמש, ולכן כאן ה-profiler של mongod (``tests/_mongo_profiler.py``) רושם
מה נקרא באמת, מול האינדקסים שהבנאים האמיתיים בונים.

**תנאי השאילתה של הטוקן האישי.** ``_not_expired_condition`` הוא ``_is_expired`` כתוב כשאילתה, וכאן
הוא נבדק במונגו עצמו: ``$not`` תופס גם שדה חסר, ודמה רק מחקה את זה.

**פתק על לוח.** פתק קובץ ופתק ריפו נכתבים בלי ``board_id`` בכלל, ו-``any_board_note_filter`` מוציא
אותם רק כי ``$nin`` שכולל ``null`` מוציא גם שדה חסר. זה הפוך ממה שמשתמע מהתיעוד של ``$nin``
(ההסבר ב-``docs/testing.rst``), ולכן זה נבדק כאן מול השרת, על פתקים שבונה הכותב האמיתי.

**"הצג שוב" מול הנעילה.** ``asked_to_see_again`` ו-``_NOT_ASKED_TO_SEE_AGAIN`` הם אותו כלל, בפייתון
וכתנאי שאילתה. כאן נבדקים המקרים שהדמה לא יודעת לענות עליהם כמו מונגו: ``0``, ומערך בדרך. וגם הכתיבה
המותנית של הנעילה, על השרת.

מדולג בלי מונגו (``wired_mongo``). ב-CI הכתובת שמוגדרת אינה נגישה, ולכן הבדיקות האלה מדלגות שם —
ראו את ההערה ב-``.github/workflows/ci.yml`` ואת ``docs/testing.rst``. בדיקות ה-CI של אותן פונקציות,
על דמה: ``tests/test_first_steps.py``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _mongo_profiler import profiled

import mcp_server.oauth_store as oauth_store
import mcp_server.token_store as token_store
from mcp_server.oauth_store import ACCESS_PREFIX, REFRESH_PREFIX, OAuthStore, new_secret
from sticky_notes_target import any_board_note_filter, build_note_target
from webapp import first_steps

SUBJECT = "7"

#: רענונים של לקוח אחד שנשאר מחובר. כל רענון משאיר שורת refresh מבוטלת, ולכן אחריהם יש מאות שורות
#: ל-``subject`` — ושאילתה שעוברת על כולן קוראת את כולן.
ROTATIONS = 300


def test_the_oauth_check_reads_one_document_of_a_long_rotation_chain(wired_mongo):
    db = wired_mongo.get_db()
    store = OAuthStore(db)  # האינדקסים של הייצור: ``subject``, ``expires_at`` (TTL) ו-``token_hash``
    presented = None
    for _ in range(ROTATIONS):
        # כמו ``exchange_refresh_token`` ו-``_issue`` ב-``mcp_server/oauth_provider.py``: ה-refresh שהוגש
        # מבוטל, ונכתב זוג חדש. השורה המבוטלת נשארת עד ה-``expires_at`` שלה.
        if presented is not None:
            assert store.revoke_token(presented) is True
        store.save_token(new_secret(ACCESS_PREFIX), kind="access", data={"client_id": "c1", "subject": SUBJECT})
        presented = new_secret(REFRESH_PREFIX)
        store.save_token(presented, kind="refresh", data={"client_id": "c1", "subject": SUBJECT})

    with profiled(db) as entries:
        assert oauth_store.subject_has_live_token(db, SUBJECT) is True

    reads = [
        entry for entry in entries
        if entry.get("ns") == f"{db.name}.{oauth_store.TOKENS_COLLECTION}" and entry.get("op") == "query"
    ]
    assert len(reads) == 1, reads
    assert reads[0]["docsExamined"] <= 2, reads[0]


def test_the_personal_token_condition_is_the_rule_on_mongod(wired_mongo):
    """``_not_expired_condition`` מול ``_is_expired``, על mongod ולא על דמה שמחקה את ``$not``."""
    db = wired_mongo.get_db()
    # BSON שומר מילישניות: רגע בלי חלק תת-מילישניה, כדי ש"הרגע עצמו" יחזור מהמסד כמו שנכתב.
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    cases = {
        "missing": {},
        "none": {"expires_at": None},
        "expired": {"expires_at": now - timedelta(seconds=1)},
        "this_instant": {"expires_at": now},
        "future": {"expires_at": now + timedelta(seconds=1)},
    }
    probe = db["first_steps_expiry_condition"]
    probe.insert_many([{"case": name, **fields} for name, fields in cases.items()])

    matched = {doc["case"] for doc in probe.find({"expires_at": token_store._not_expired_condition(now)})}
    live = {doc["case"] for doc in probe.find({}) if not token_store._is_expired(doc.get("expires_at"), now)}
    assert matched == live == {"missing", "none", "this_instant", "future"}


def test_the_board_note_filter_skips_file_and_repo_notes_on_mongod(wired_mongo):
    targets = {
        "file": build_note_target(file_id="f1"),
        "repo": build_note_target(repo_name="amirbiron/CodeBot", repo_path="README.md"),
        "board": build_note_target(board_id="b1"),
    }
    assert [kind for kind, target in targets.items() if "board_id" in target] == ["board"], (
        "פתק קובץ ופתק ריפו נכתבים בלי board_id — זה המקרה שהטסט בודק"
    )
    notes = wired_mongo.get_db()["sticky_notes"]
    notes.insert_many([{"user_id": 7, "kind": kind, **target} for kind, target in targets.items()])
    notes.insert_one({"user_id": 8, "kind": "board", **build_note_target(board_id="b2")})

    assert [doc["kind"] for doc in notes.find(any_board_note_filter(7))] == ["board"]


def test_asking_to_see_again_is_its_query_condition_on_mongod(wired_mongo):
    """הכלל בפייתון מול תנאי השאילתה, על השרת. הם חלוקים רק כשיש מערך בדרך, כמו שכתוב ליד התנאי."""
    hidden = first_steps.HIDDEN_PREF
    cases = {
        "missing": {"ui_prefs": {}},
        "no_ui_prefs": {},
        "none": {"ui_prefs": {hidden: None}},
        "true": {"ui_prefs": {hidden: True}},
        "false": {"ui_prefs": {hidden: False}},
        "zero": {"ui_prefs": {hidden: 0}},
        "one": {"ui_prefs": {hidden: 1}},
        "string_false": {"ui_prefs": {hidden: "false"}},
        "empty_string": {"ui_prefs": {hidden: ""}},
        "subdocument": {"ui_prefs": {hidden: {}}},
        "empty_array": {"ui_prefs": {hidden: []}},
        "array_without_false": {"ui_prefs": {hidden: [True]}},
        "array_with_false": {"ui_prefs": {hidden: [True, False]}},
        "ui_prefs_is_an_array": {"ui_prefs": [{hidden: False}]},
    }
    probe = wired_mongo.get_db()["first_steps_asked_condition"]
    probe.insert_many([{"case": name, **fields} for name, fields in cases.items()])

    lockable = {doc["case"] for doc in probe.find(first_steps._NOT_ASKED_TO_SEE_AGAIN)}
    not_asked = {name for name, fields in cases.items() if not first_steps.asked_to_see_again(fields)}
    assert lockable - not_asked == set()
    assert not_asked - lockable == {"array_with_false", "ui_prefs_is_an_array"}


def test_the_lock_is_not_written_over_a_show_again_on_mongod(wired_mongo, caplog):
    """הכתיבה המותנית על השרת: מסמך שבו המשתמש ביקש לראות את הכרטיס לא ננעל, ולא נוצר לו מסמך שני.

    בלי האינדקס הייחודי על ``user_id``, בכוונה. איתו, ``upsert`` שיחזור לכתיבה היה נגמר ב-
    ``DuplicateKeyError`` שנבלע כאזהרה; בלעדיו הוא מייצר מסמך כפול, והטסט נופל.
    """
    users = wired_mongo.get_db()["users"]
    users.insert_one({"user_id": 7, "ui_prefs": {first_steps.HIDDEN_PREF: False}})

    with caplog.at_level(logging.INFO, logger="webapp.first_steps"):
        first_steps._write_lock(wired_mongo.get_db(), 7)
        first_steps._write_lock(wired_mongo.get_db(), 8)  # למשתמש 8 אין מסמך

    docs = list(users.find({}, {"_id": 0}))
    assert docs == [{"user_id": 7, "ui_prefs": {first_steps.HIDDEN_PREF: False}}], docs
    messages = [r.getMessage() for r in caplog.records]
    assert sum(m.startswith("first steps: the lock was not written") for m in messages) == 2, messages
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], messages
