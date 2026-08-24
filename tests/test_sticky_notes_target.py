"""בדיקות ל-``sticky_notes_target`` — האילוץ "בדיוק אחד" ותקרת הפתקים.

המודול טהור, ולכן הבדיקות כאן לא נוגעות ב-Flask, ב-pymongo ובשום stub. זה
בדיוק מה שהמודול נועד לאפשר: את הכלל שקובע לאיזה משטח פתק שייך אפשר לבדוק
בלי להרים אפליקציה.
"""

import pytest

from sticky_notes_target import (
    DEFAULT_BOARD_MODE,
    MAX_NOTES_PER_REPO_FILE,
    NOTE_MODES,
    ONE_TITLE_PER_REPO_FILE_INDEX,
    NoteQuotaError,
    NoteTargetError,
    board_notes_filter,
    build_note_target,
    check_note_quota,
    file_notes_filter,
    is_valid_mode,
    normalize_mode,
    normalize_repo_path,
    repo_notes_filter,
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


# ---------- נרמול שם פתק ----------


def test_title_is_trimmed_and_collapsed_to_one_line():
    from sticky_notes_target import normalize_note_title

    assert normalize_note_title("  רשימת   מטלות \n שנייה ") == "רשימת מטלות שנייה"


def test_blank_title_means_no_title():
    from sticky_notes_target import normalize_note_title

    assert normalize_note_title("") == ""
    assert normalize_note_title("   \t\n ") == ""
    assert normalize_note_title(None) == ""


def test_title_is_capped():
    from sticky_notes_target import MAX_NOTE_TITLE, normalize_note_title

    assert len(normalize_note_title("א" * 500)) == MAX_NOTE_TITLE


@pytest.mark.parametrize(
    "value",
    [["a", "b"], {"x": 1}, 42, 3.5, True, object()],
)
def test_only_a_string_can_be_a_title(value):
    """**ייצוג פייתון פנימי לא נכנס למסד כשם פתק.**

    ``str(value)`` על גוף JSON שרירותי הופך ``["a", "b"]`` למחרוזת
    ``"['a', 'b']"`` — שם מעוות שנשמר, מוצג למשתמש, ותופס מקום באינדקס
    הייחודי. כל טיפוס שאינו ``str`` נחשב "אין שם", כמו מחרוזת ריקה.

    נופלת אם הנרמול חוזר ל-``str(value or "")``.
    """
    from sticky_notes_target import normalize_note_title

    assert normalize_note_title(value) == ""


# -- יעד שלישי: קובץ בריפו ממורר --

def test_repo_target_is_accepted():
    """הזוג ``(repo_name, repo_path)`` הוא יעד חוקי, בדיוק כמו קובץ או לוח."""
    validate_note_target({"repo_name": "CodeBot", "repo_path": "webapp/app.py"})


@pytest.mark.parametrize(
    "doc",
    [
        {"repo_name": "CodeBot"},
        {"repo_path": "webapp/app.py"},
        {"repo_name": "CodeBot", "repo_path": "   "},
    ],
)
def test_half_a_repo_target_is_rejected(doc):
    """חצי יעד אינו יעד.

    ``repo_name`` בלי ``repo_path`` אינו מזהה קובץ, ו-``repo_path`` בלי
    ``repo_name`` אינו יודע באיזה ריפו. שניהם היו מייצרים פתק שלא נמצא
    בשום שאילתה — בדיוק המצב שנעלם בשקט.

    נופלת אם הזיהוי מסתפק בשדה אחד מהשניים.
    """
    with pytest.raises(NoteTargetError):
        validate_note_target(doc)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"repo_name": "CodeBot", "repo_path": "a.py", "file_id": "abc"},
        {"repo_name": "CodeBot", "repo_path": "a.py", "board_id": "b1"},
    ],
)
def test_repo_target_cannot_combine_with_other_targets(kwargs):
    """יעד ריפו + יעד אחר = שני מקומות לפתק אחד.

    נופלת אם המעבר לטרנרי לא נעשה והזיהוי נשאר בינארי.
    """
    with pytest.raises(NoteTargetError):
        build_note_target(**kwargs)


def test_repo_target_rejects_file_metadata():
    """``scope_id``/``file_name`` הם מושגים של קובץ CodeKeeper, לא של ריפו.

    זו בדיוק ההפרה שהכלל התכונתי תופס בלי שמישהו ימנה אותה מראש: השדה
    שייך לסוג ``file``, והסוג שנבחר הוא ``repo``.
    """
    with pytest.raises(NoteTargetError):
        build_note_target(repo_name="CodeBot", repo_path="a.py", scope_id="user:1:file:dead")
    with pytest.raises(NoteTargetError):
        build_note_target(repo_name="CodeBot", repo_path="a.py", file_name="a.md")


def test_build_repo_target_normalizes_on_write():
    """הנורמליזציה רצה **בכתיבה**, לא רק בקריאה."""
    assert build_note_target(repo_name="CodeBot", repo_path="/webapp//app.py") == {
        "repo_name": "CodeBot",
        "repo_path": "webapp/app.py",
    }


# -- נורמליזציית נתיב --

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("webapp/app.py", "webapp/app.py"),
        ("/webapp/app.py", "webapp/app.py"),
        ("webapp//app.py", "webapp/app.py"),
        ("webapp\\app.py", "webapp/app.py"),
        ("./webapp/app.py", "webapp/app.py"),
        ("webapp/../webapp/app.py", "webapp/app.py"),
        ("  webapp/app.py  ", "webapp/app.py"),
    ],
)
def test_repo_path_normalizes_to_repo_files_form(raw, expected):
    """**היעד הוא הצורה ש-``repo_files.path`` שומר**, לא "עקביות פנימית".

    ``services/code_indexer.py`` שומר את הנתיב כפי שהוא מגיע מ-git —
    לוכסנים קדימה, בלי ``/`` מוביל. גילוי היתומים משווה מול המניפסט הזה,
    ולכן כל צורה אחרת מסמנת קובץ קיים כמיותם.

    ``..`` פנימי **נפתר** (הוא נתיב לגיטימי בתוך הריפו); רק בריחה מעל
    השורש נפסלת — ראו הטסט הבא.

    נופלת אם ההסרה של ``/`` המוביל או כיווץ הלוכסנים מושמטים.
    """
    assert normalize_repo_path(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["../etc/passwd", "..", "/../x", "a/../../b", "", "   ", None, "/", "."],
)
def test_repo_path_rejects_escape_above_root(raw):
    """בריחה מעל שורש הריפו נדחית ל-``""``.

    **``/../x`` הוא המקרה שמצדיק את המימוש הידני:** ``posixpath.normpath``
    פותר ``/..`` אל השורש ומחזיר ``x`` — בריחה שנראית תמימה אחרי נרמול.
    לכן החריגה נבדקת בזמן הפתרון, כשעדיין ידוע שירדנו מתחת לשורש.

    ובזכות הדחייה הפתק גם לא נוצר: ``repo_path`` ריק הוא יעד חצוי.

    נופלת אם מנרמלים קודם ובודקים ``..`` אחר כך.
    """
    assert normalize_repo_path(raw) == ""


def test_note_written_unnormalized_is_found():
    """**הטסט המרכזי של הנורמליזציה: שני הקצוות מתכנסים.**

    פתק שנכתב עם נתיב לא-מנורמל חייב להימצא בשאילתה שנבנית מכל צורה
    שקולה. אחרת השאילתה רצה, מחזירה אפס, ולא זורקת כלום — הכשל השקט
    הקלאסי.

    נופלת אם הנורמליזציה מופעלת רק בצד אחד.
    """
    written = build_note_target(repo_name="CodeBot", repo_path="/docs//guide.rst")
    for lookup in ("/docs//guide.rst", "docs/guide.rst", "./docs/guide.rst"):
        q = repo_notes_filter(7, "CodeBot", lookup)
        assert q["repo_path"] == written["repo_path"]
        assert q["repo_name"] == written["repo_name"]


# -- אי-דליפה בשלושה כיוונים --

def test_no_leak_between_the_three_filters():
    """שאילתה של סוג אחד אינה תופסת פתק מסוג אחר.

    פתק ריפו אין לו ``file_id``/``scope_id``/``board_id``, ופתק קובץ/לוח
    אין לו ``repo_name`` — ולכן אין דליפה ולא נדרש שומר. הטסט מקבע את
    המסקנה, כדי שאם מישהו יוסיף ברירת מחדל לשדה כלשהו — היא תיפול.
    """
    repo_note = build_note_target(repo_name="CodeBot", repo_path="a.py")
    file_note = build_note_target(file_id="abc")
    board_note = build_note_target(board_id="b1")

    repo_q = repo_notes_filter(7, "CodeBot", "a.py")
    file_q = file_notes_filter(7, "user:1:file:dead", ["abc"])
    board_q = board_notes_filter(7, "b1")

    assert set(repo_q) == {"user_id", "repo_name", "repo_path"}
    assert "repo_name" not in file_note and "repo_name" not in board_note
    assert "board_id" in board_q and "board_id" not in repo_note
    assert "$or" in file_q
    assert "file_id" not in repo_note and "scope_id" not in repo_note


# -- מכסה: הקבוע שלא היה נאכף --

def test_repo_file_cap_enforced_even_for_admin():
    """**דפדפן הריפו חסום לאדמינים — כלומר כל מי שמגיע לפיצ'ר הוא אדמין.**

    אם ה-cap-לקובץ נקרא עם ``is_admin=True`` (כמו תקרת המשתמש), הוא לא
    נאכף על אף אחד לעולם: קבוע מת שנראה חי. מטרתו שמירת צורת-תוכן ולא
    הגנת-משאבים, ולכן הקורא מעביר ``is_admin=False`` תמיד.

    נופלת אם הקורא יעביר את ``is_admin`` האמיתי.
    """
    with pytest.raises(NoteQuotaError):
        check_note_quota(MAX_NOTES_PER_REPO_FILE, MAX_NOTES_PER_REPO_FILE, is_admin=False)


def test_repo_quota_fail_closed_on_count_error():
    """כשל ספירה נסגר ולא נפתח — גם כאן, ועם ``is_admin=False``.

    (עם ``is_admin=True`` הטסט היה עובר בלי לבדוק כלום: הפטור מקדים את
    בדיקת ה-``None``.)
    """
    with pytest.raises(NoteQuotaError):
        check_note_quota(None, MAX_NOTES_PER_REPO_FILE, is_admin=False)


# -- האינדקס המקביל --

def test_repo_title_index_is_partial_on_repo_path():
    """הפילטר דורש ``repo_path`` קיים — כמו שאח שלו דורש ``board_id``.

    בלי זה, פתקי קובץ/לוח (שאין להם ``repo_path``) היו נכנסים לאינדקס עם
    ערך חסר, חולקים מפתח, ושני פתקים שונים עם אותו שם היו נדחים ב-E11000.
    """
    pfe = ONE_TITLE_PER_REPO_FILE_INDEX["partialFilterExpression"]
    assert pfe == {"title": {"$exists": True}, "repo_path": {"$exists": True}}
    assert ONE_TITLE_PER_REPO_FILE_INDEX["unique"] is True
    assert [f for f, _ in ONE_TITLE_PER_REPO_FILE_INDEX["keys"]] == [
        "user_id",
        "repo_name",
        "repo_path",
        "title",
    ]
    assert ONE_TITLE_PER_REPO_FILE_INDEX["name"].endswith("_v1")
