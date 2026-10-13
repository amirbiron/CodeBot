"""``note_threads`` — הכללים של שרשורי התגובות, בלי מסד.

מה שתלוי במסד (הפעולות האטומיות, התקרות בפילטר, הבידוד בין משתמשים) נבדק מול מונגו אמיתי
ב-``tests/test_note_threads_mongo.py``, ודרך כלי ה-MCP ב-``tests/test_note_threads_mcp.py``.
כאן — מה שהמודול מחליט לבד: מה נדחה, איך נקרא הכותב, כמה בתים גוף שוקל, ומה אירוע ההתראה
נושא.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import note_threads as nt

ROOT = Path(__file__).resolve().parents[1]
NOTE = "a" * 24


# -- גוף תגובה -------------------------------------------------------------------


@pytest.mark.parametrize("body", ["x", "  padded  \n", "&amp; <b> \r\n", "\x07 bell", "א" * nt.MAX_COMMENT_CHARS])
def test_a_body_within_the_rules_is_accepted_as_is(body):
    """בלי ניקוי: ישויות, CRLF, תווי בקרה ורווחים בקצוות — כולם עוברים כמו שהם."""
    assert nt.comment_body_error(body) is None


def test_the_body_rules_refuse_rather_than_cut():
    assert nt.comment_body_error(None) == {"ok": False, "error": "invalid_body"}
    assert nt.comment_body_error(5) == {"ok": False, "error": "invalid_body"}
    assert nt.comment_body_error(" \n\t ") == {"ok": False, "error": "empty_body"}
    assert nt.comment_body_error("x" * (nt.MAX_COMMENT_CHARS + 1)) == {
        "ok": False, "error": "body_too_long", "max": nt.MAX_COMMENT_CHARS,
    }
    # surrogate בודד — BSON ו-JSON לא יישאו אותו.
    assert nt.comment_body_error("a\ud800b") == {"ok": False, "error": "invalid_body"}


def test_the_length_is_counted_in_characters_not_bytes():
    """4,000 תווים עבריים הם 8,000 בתים — והם עדיין בתוך התקרה (H6)."""
    hebrew = "ש" * nt.MAX_COMMENT_CHARS
    assert len(hebrew.encode("utf-8")) == 2 * nt.MAX_COMMENT_CHARS
    assert nt.comment_body_error(hebrew) is None


# -- working_on -------------------------------------------------------------------


def test_working_on_is_normalized_to_one_line():
    assert nt.working_on_or_error("  העברת תיקון\n bidi  ל-Ck ") == "העברת תיקון bidi ל-Ck"


def test_working_on_missing_empty_or_too_long_is_refused():
    assert nt.working_on_or_error(None) == {
        "ok": False, "error": "working_on_required", "max": nt.MAX_WORKING_ON_CHARS,
    }
    assert nt.working_on_or_error(" \n ") == {
        "ok": False, "error": "working_on_required", "max": nt.MAX_WORKING_ON_CHARS,
    }
    assert nt.working_on_or_error(["task"]) == {"ok": False, "error": "invalid_working_on"}
    assert nt.working_on_or_error("x" * (nt.MAX_WORKING_ON_CHARS + 1)) == {
        "ok": False, "error": "working_on_too_long", "max": nt.MAX_WORKING_ON_CHARS,
    }
    # בתקרה בדיוק — עובר; הנרמול לפני המדידה.
    assert nt.working_on_or_error(" " + "y" * nt.MAX_WORKING_ON_CHARS + " ") == "y" * nt.MAX_WORKING_ON_CHARS


# -- מי כתב -------------------------------------------------------------------------


@pytest.mark.parametrize(("client", "label"), [
    ("claude-code", "CC"),
    ("Anthropic/ClaudeAI", "Claude"),
    ("Gemini", "Gemini"),
    ("cursor-vscode", "cursor-vscode"),
    (None, nt.UNKNOWN_AGENT_LABEL),
])
def test_the_author_label_follows_the_spec_table(client, label):
    """הטבלה "מי כתב" שבאפיון. שלושת השמות הראשונים נצפו בייצור (לוח ה-MCP בוובאפ)."""
    author = nt.agent_author(client=client, working_on="אפיון שרשורי תגובות")
    assert nt.author_label(author, user_name="אמיר") == label


def test_a_user_comment_is_labelled_with_the_users_name():
    assert nt.author_label(nt.user_author(), user_name="נועה") == "נועה"
    assert nt.user_author() == {"kind": "user", "client": None, "working_on": None}


def test_the_client_name_is_one_bounded_line_or_unknown():
    assert nt.normalize_client_name("  claude-code \n") == "claude-code"
    assert nt.normalize_client_name("c" * 200) == "c" * nt.MAX_CLIENT_NAME_CHARS
    assert nt.normalize_client_name("") is None
    assert nt.normalize_client_name(42) is None
    assert nt.normalize_client_name("a\ud800") is None


def test_an_author_not_built_by_the_module_is_a_bug_not_input():
    """הכותב נבנה בקוד שלנו; צורה אחרת עולה כשגיאה ולא נשמרת."""
    with pytest.raises(ValueError):
        nt._checked_author({"kind": "agent", "client": "x", "working_on": "x" * 500})
    with pytest.raises(ValueError):
        nt._checked_author({"kind": "user", "client": "claude-code", "working_on": None})
    with pytest.raises(ValueError):
        nt._checked_author({"kind": "admin"})


# -- גודל הגוף כפי שהוא נשלח -----------------------------------------------------------


def test_body_wire_bytes_is_what_the_mcp_server_measures():
    """``body_wire_bytes`` הוא בדיוק מה ש-``answer_size.wire_json`` כותב למחרוזת.

    התקרה ``MAX_THREAD_BODY_BYTES`` נאכפת במסד מול הסכום הזה, והשרת מודד את התשובה ב-
    ``wire_json``; אילו נבדלו, שרשור "בתוך התקרה" היה יכול שלא להיכנס בתשובה. הקורפוס
    מכסה את כל מה ש-JSON מטפל בו אחרת: תווי בקרה, מירכאות, לוכסן הפוך, ASCII, עברית,
    אימוג'י (4 בתים), ומפרידי השורות של יוניקוד.
    """
    from mcp_server.answer_size import wire_json

    corpus = ["", "plain", '"quoted" \\ back', "\x00\x01\x1f\x7f", "\t\n\r", "שלום",
              "😀🙂", "  ", "<>&'", "a‏b", "﻿", "x" * 5000]
    corpus += [chr(cp) for cp in range(0, 0x3000, 7) if not 0xD800 <= cp <= 0xDFFF]
    for text in corpus:
        assert nt.body_wire_bytes(text) == len(wire_json(text)), repr(text)


# -- מזהים ------------------------------------------------------------------------------


def test_a_thread_id_from_the_client_is_checked_before_use():
    assert nt.parse_thread_id("AB" * 12) == "ab" * 12
    assert nt.parse_thread_id(" " + "a" * 24 + " ") == "a" * 24
    for bad in (None, 5, "", "a" * 23, "g" * 24, {"$ne": None}, ["a" * 24]):
        assert nt.parse_thread_id(bad) is None, bad


def test_the_scope_refuses_a_non_canonical_note_id():
    """מזהה פתק באותיות גדולות היה כותב שרשור שאף קריאה לא תמצא."""
    assert nt.thread_scope(7, NOTE) == {"user_id": 7, "note_id": NOTE}
    for bad in ("A" * 24, "a" * 23, None, 5):
        with pytest.raises(ValueError):
            nt.thread_scope(7, bad)


# -- סדר התצוגה -------------------------------------------------------------------------


def test_open_threads_come_first_newest_activity_first():
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    rows = [
        {"number": 1, "status": "resolved", "last_at": t0 + timedelta(days=9)},
        {"number": 2, "status": "open", "last_at": t0 + timedelta(days=1)},
        {"number": 3, "status": "open", "last_at": t0 + timedelta(days=5)},
        {"number": 4, "status": "resolved", "last_at": t0},
        {"number": 5, "status": "open", "last_at": None},
    ]
    assert [r["number"] for r in nt.display_order(rows)] == [3, 2, 5, 1, 4]


# -- אירוע ההתראה -----------------------------------------------------------------------


def test_the_push_event_carries_ids_and_where_the_note_sits():
    author = nt.agent_author(client="claude-code", working_on="תיקון bidi")
    when = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
    event = nt.note_comment_push_event(
        user_id=7, note_id=NOTE, thread_id="b" * 24, comment_id="c" * 24, author=author,
        target_ref={"target": "board", "board_id": "d" * 24, "junk": "x"}, now=when,
    )
    assert event == {
        "user_id": 7, "kind": "note_comment", "note_id": NOTE, "thread_id": "b" * 24,
        "comment_id": "c" * 24, "target": "board", "board_id": "d" * 24,
        "author": {"kind": "agent", "client": "claude-code", "working_on": "תיקון bidi"},
        "created_at": when, "needs_push": True,
    }


def test_a_users_own_comment_never_notifies_the_user():
    with pytest.raises(ValueError):
        nt.note_comment_push_event(
            user_id=7, note_id=NOTE, thread_id="b" * 24, comment_id="c" * 24,
            author=nt.user_author(), target_ref={},
        )


# -- אינדקסים וטוהר המודול ---------------------------------------------------------------


def test_the_indexes_are_the_two_the_spec_names_and_only_performance_ones():
    specs = nt.note_threads_indexes()
    assert [s["keys"] for s in specs] == [
        [("user_id", 1), ("note_id", 1)],
        [("user_id", 1), ("status", 1), ("last_author_kind", 1)],
    ]
    assert all(set(s) == {"keys", "name"} for s in specs)  # בלי unique, TTL או פילטר חלקי


def test_importing_the_module_pulls_no_database_or_web_framework():
    """מודול שורש טהור: הוובאפ ושירות ה-MCP מייבאים אותו, ואין בו תופעת לוואי בייבוא."""
    code = (
        "import sys; import note_threads; "
        "bad = sorted(m for m in ('pymongo', 'bson', 'flask', 'mcp_server', 'database') if m in sys.modules); "
        "print(','.join(bad))"
    )
    out = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, capture_output=True, text=True,
                         check=True)
    assert out.stdout.strip() == ""
