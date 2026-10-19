"""בדיקות החיבור של הצ'קליסט "צעדים ראשונים" מול mongod אמיתי — מה שדמה לא יכולה להראות.

**כמה השרת קורא.** "יש חיבור חי?" צריכה מסמך אחד מהשרת. דמה מחזירה את אותה תשובה גם כשהשרת
עובר על כל השורות של המשתמש, ולכן כאן ה-profiler של mongod (``tests/_mongo_profiler.py``) רושם
מה נקרא באמת, מול האינדקסים שהבנאים האמיתיים בונים.

**תנאי השאילתה של הטוקן האישי.** ``_not_expired_condition`` הוא ``_is_expired`` כתוב כשאילתה, וכאן
הוא נבדק במונגו עצמו: ``$not`` תופס גם שדה חסר, ודמה רק מחקה את זה.

**פתק על לוח.** פתק קובץ ופתק ריפו נכתבים בלי ``board_id`` בכלל, ו-``any_board_note_filter`` מוציא
אותם רק כי ``$nin`` שכולל ``null`` מוציא גם שדה חסר. זה הפוך ממה שמשתמע מהתיעוד של ``$nin``
(ההסבר ב-``docs/testing.rst``), ולכן זה נבדק כאן מול השרת, על פתקים שבונה הכותב האמיתי.

מדולג בלי מונגו (``wired_mongo``). ב-CI הכתובת שמוגדרת אינה נגישה, ולכן הבדיקות האלה מדלגות שם —
ראו את ההערה ב-``.github/workflows/ci.yml`` ואת ``docs/testing.rst``. בדיקות ה-CI של אותן פונקציות,
על דמה: ``tests/test_first_steps.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

# ``tests`` אינו חבילה — ראה את ה-docstring של ``tests/conftest.py``.
from _mongo_profiler import profiled

import mcp_server.oauth_store as oauth_store
import mcp_server.token_store as token_store
from mcp_server.oauth_store import ACCESS_PREFIX, REFRESH_PREFIX, OAuthStore, new_secret
from sticky_notes_target import any_board_note_filter, build_note_target

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
