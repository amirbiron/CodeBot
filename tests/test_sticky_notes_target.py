"""בדיקות ל-``sticky_notes_target`` — האילוץ "בדיוק אחד" ותקרת הפתקים.

המודול טהור, ולכן הבדיקות כאן לא נוגעות ב-Flask, ב-pymongo ובשום stub. זה
בדיוק מה שהמודול נועד לאפשר: את הכלל שקובע לאיזה משטח פתק שייך אפשר לבדוק
בלי להרים אפליקציה.
"""

import pytest

from sticky_notes_target import (
    DEFAULT_BOARD_MODE,
    NOTE_MODES,
    NoteQuotaError,
    NoteTargetError,
    board_notes_filter,
    build_note_target,
    check_note_quota,
    file_notes_filter,
    is_valid_mode,
    normalize_mode,
    validate_note_target,
)


# -- validate_note_target --

def test_both_targets_is_rejected():
    """פתק ששייך גם לקובץ וגם ללוח אינו חוקי — אין לו מקום אחד."""
    with pytest.raises(NoteTargetError):
        validate_note_target({"file_id": "abc", "board_id": "xyz"})


def test_no_target_is_rejected():
    """פתק בלי משטח אינו נראה בשום מקום בממשק. עדיף שייכשל בכתיבה."""
    with pytest.raises(NoteTargetError):
        validate_note_target({})


def test_blank_string_counts_as_empty():
    """``''`` ורווחים אינם יעד.

    זה לא תיאורטי: ``_as_note_response`` מחזיר ``str(doc.get('file_id', ''))``,
    כלומר מחרוזת ריקה היא ערך שבאמת מסתובב במערכת, ו-``set_note_reminder``
    כותב אותה למסמך התזכורת.
    """
    with pytest.raises(NoteTargetError):
        validate_note_target({"file_id": "   ", "board_id": ""})


def test_exactly_one_target_passes():
    validate_note_target({"file_id": "abc"})
    validate_note_target({"board_id": "xyz"})


# -- build_note_target --

def test_build_runs_validation_before_returning():
    """הבנאי אינו יכול להחזיר מסמך לא חוקי — גם לא כשלא הועבר לו כלום."""
    with pytest.raises(NoteTargetError):
        build_note_target()
    with pytest.raises(NoteTargetError):
        build_note_target(file_id="abc", board_id="xyz")


def test_build_file_target_carries_scope_fields():
    target = build_note_target(file_id="abc", scope_id="user:1:file:deadbeef", file_name="a.md")
    assert target == {
        "file_id": "abc",
        "scope_id": "user:1:file:deadbeef",
        "file_name": "a.md",
    }


def test_build_file_target_omits_empty_scope_fields():
    """בדיוק כמו הראוט היום: ``scope_id``/``file_name`` נכתבים רק אם נפתרו."""
    assert build_note_target(file_id="abc") == {"file_id": "abc"}


def test_build_board_target_is_minimal():
    assert build_note_target(board_id="b1") == {"board_id": "b1"}


def test_board_target_rejects_file_metadata():
    """``scope_id``/``file_name`` הם מושגים של קובץ.

    השלמה שקטה שלהם על פתק לוח הייתה מכניסה אותו לשאילתת הקובץ — כלומר פתק
    שמופיע בשני מקומות. עדיף להיכשל אצל הקורא.
    """
    with pytest.raises(NoteTargetError):
        build_note_target(board_id="b1", scope_id="user:1:file:deadbeef")
    with pytest.raises(NoteTargetError):
        build_note_target(board_id="b1", file_name="a.md")


# -- filters --

def test_file_filter_matches_the_existing_route_shape():
    """צורת השאילתה זהה למה שהראוט בנה בידיים, כולל סדר הענפים."""
    assert file_notes_filter(7, "user:7:file:abc", ["id1", "id2"]) == {
        "user_id": 7,
        "$or": [{"scope_id": "user:7:file:abc"}, {"file_id": {"$in": ["id1", "id2"]}}],
    }


def test_file_filter_falls_back_to_file_id_without_scope():
    assert file_notes_filter(7, None, [], file_id="f1") == {"user_id": 7, "file_id": "f1"}


def test_board_filter_is_direct():
    """בלי ``$or`` ובלי ``code_snippets`` — שאילתה אחת על אינדקס אחד."""
    assert board_notes_filter(7, "b1") == {"user_id": 7, "board_id": "b1"}


def test_filters_cannot_catch_each_others_notes():
    """אין דליפה בין הכיוונים — וזו הסיבה שלא נדרש שומר נוסף בראוטים.

    פתק לוח לא נושא ``scope_id`` ולא ``file_id``, ושלושת הענפים של שאילתת
    הקובץ דורשים אחד מהם. פתק קובץ לא נושא ``board_id``.
    """
    file_q = file_notes_filter(7, "user:7:file:abc", ["id1"])
    board_q = board_notes_filter(7, "b1")

    board_note = {"user_id": 7, "board_id": "b1"}
    file_note = {"user_id": 7, "file_id": "id1", "scope_id": "user:7:file:abc"}

    # שאילתת הקובץ אינה נוגעת בפתק לוח: אף ענף ב-$or אינו מזכיר שדה שקיים בו
    assert all(key not in board_note for clause in file_q["$or"] for key in clause)
    # ושאילתת הלוח אינה נוגעת בפתק קובץ: היא דורשת board_id שאין לו
    assert "board_id" in board_q
    assert "board_id" not in file_note


# -- modes --

def test_default_mode_is_surface():
    """ברירת המחדל בלוח היא הצמדה למשטח — הלוח *הוא* המשטח."""
    assert DEFAULT_BOARD_MODE == "surface"
    assert normalize_mode(None) == "surface"
    assert normalize_mode("") == "surface"


def test_unknown_mode_falls_back_but_is_not_valid():
    """``normalize_mode`` סלחני לקלט משתמש; ``is_valid_mode`` הוא זה שדוחה 400."""
    assert normalize_mode("nonsense") == "surface"
    assert is_valid_mode("nonsense") is False
    assert is_valid_mode("screen") is True


def test_anchored_is_reserved_but_recognized():
    """``anchored`` שמור לפתקי קבצים כשיעברו לשדה אמיתי.

    הוא ברשימה מראש כדי שהמעבר לא ידרוש שינוי שם של ערך קיים.
    """
    assert "anchored" in NOTE_MODES
    assert is_valid_mode("anchored") is True


# -- check_note_quota --

def test_quota_blocks_at_cap():
    with pytest.raises(NoteQuotaError):
        check_note_quota(200, 200)


def test_quota_allows_below_cap():
    check_note_quota(199, 200)


def test_admin_is_exempt():
    check_note_quota(10_000, 200, is_admin=True)


def test_failed_count_is_rejected_not_waved_through():
    """כשל ספירה ⇒ דחייה.

    ``mcp_server/backend`` עושה כאן את ההפך: ``existing = 0`` בכשל, כלומר
    התקרה נפתחת לרווחה בדיוק כשהמסד מתקשה. הבדיקה הזו נופלת אם מעתיקים את
    ההתנהגות ההיא לכאן.
    """
    with pytest.raises(NoteQuotaError):
        check_note_quota(None, 200)


def test_admin_exempt_even_when_count_failed():
    """הפטור קודם לכל בדיקה אחרת — אדמין לא נחסם בגלל מסד שמתקשה."""
    check_note_quota(None, 200, is_admin=True)
