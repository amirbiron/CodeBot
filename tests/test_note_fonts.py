"""גופן הפתקים: הכרעת התחולה, ה-API, וההפרדה בין המשטחים.

**מה שנבדק כאן ומה שלא.** הכרעת התחולה והקידוד נבדקים כפונקציות טהורות,
ולכן אינם דורשים מסד. מסלול ה-API — מה נכתב ל-DB ומה נכתב ל-cookie —
נבדק מול מונגו אמיתי כשיש כזה, ומדולג אחרת: בדיקה שמריצה את הראוט מול
סטאב הייתה מדווחת ירוק על מסלול שלא רץ.

הכרעת התחולה מחקה את זו של ערכת הנושא (``_resolve_theme_raw_token``):
ה-cookie של המכשיר גובר **רק** כשהתחולה היא ``device``; אחרת ה-DB.
"""

import itertools
import os

import pytest

pytest.importorskip("flask")

MONGO_URI = os.getenv("NOTE_FONTS_TEST_MONGO_URI")


@pytest.fixture
def app():
    from webapp.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app


def resolve(app, cookies, user_doc, user_id=7):
    from webapp.app import _resolve_note_fonts

    header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    with app.test_request_context("/", headers={"Cookie": header}):
        return _resolve_note_fonts(user_id, user_doc)


def _doc(repo=False, md=False, board=False):
    return {"ui_prefs": {"note_fonts": {"repo": repo, "md": md, "board": board}}}


# ── הקידוד ──────────────────────────────────────────────────────────────

def test_encode_decode_round_trip_over_every_combination():
    from webapp.app import NOTE_FONT_SURFACES, _decode_note_fonts, _encode_note_fonts

    for combo in itertools.product([False, True], repeat=len(NOTE_FONT_SURFACES)):
        fonts = dict(zip(NOTE_FONT_SURFACES, combo))
        assert _decode_note_fonts(_encode_note_fonts(fonts)) == fonts


@pytest.mark.parametrize("bad", ["abc", "1", "", "1111", "12", None, "0b1", "10a"])
def test_a_corrupt_cookie_decodes_to_none_and_does_not_raise(bad):
    """``None`` ולא ברירת מחדל — ההבחנה שכל ההכרעה תלויה בה.

    "המכשיר לא אמר כלום" נופל ל-DB; "המכשיר אמר הכל רגיל" גובר עליו.
    ערך אחד לשני המצבים היה מוחק את ההבדל.
    """
    from webapp.app import _decode_note_fonts

    assert _decode_note_fonts(bad) is None


def test_surrounding_whitespace_is_tolerated_on_purpose():
    """``.strip()`` לפני ההתאמה — אותו idiom של ``theme`` בקוד הקיים.

    זו התנהגות מכוונת ולא פרצה: הערך עדיין חייב להיות בדיוק מחרוזת
    הביטים אחרי הקיצוץ, ומה שנכתב ל-cookie עובר ``re.fullmatch`` נפרד
    בראוט לפני שהוא יוצא.
    """
    from webapp.app import _decode_note_fonts

    assert _decode_note_fonts(" 101 ") == {"repo": True, "md": False, "board": True}


# ── הכרעת התחולה ────────────────────────────────────────────────────────

def test_a_device_scoped_cookie_wins_over_the_database(app):
    got, _ = resolve(app, {"ui_note_fonts_scope": "device", "ui_note_fonts": "111"},
                     _doc())
    assert got == {"repo": True, "md": True, "board": True}


def test_a_global_device_ignores_its_own_stale_cookie(app):
    """זו ההתנגשות בין מכשירים, בשורה אחת.

    מכשיר ב-``global`` קורא מה-DB גם כשיש לו cookie ישן משלו — אחרת
    טאבלט וטלפון היו דורסים זה את זה בכל טעינת עמוד.
    """
    got, _ = resolve(app, {"ui_note_fonts_scope": "global", "ui_note_fonts": "101"},
                     _doc(md=True))
    assert got == {"repo": False, "md": True, "board": False}


def test_device_scope_without_a_cookie_falls_back_to_the_database(app):
    got, _ = resolve(app, {"ui_note_fonts_scope": "device"}, _doc(True, True, True))
    assert got == {"repo": True, "md": True, "board": True}


def test_a_corrupt_device_cookie_falls_back_to_the_database(app):
    got, _ = resolve(app, {"ui_note_fonts_scope": "device", "ui_note_fonts": "zzz"},
                     _doc(board=True))
    assert got == {"repo": False, "md": False, "board": True}


def test_an_unknown_scope_is_treated_as_global(app):
    """אותו idiom של ``_normalize_theme_scope``: נפילה לברירת מחדל, לא זריקה."""
    got, scope = resolve(app, {"ui_note_fonts_scope": "sideways", "ui_note_fonts": "111"},
                         _doc())
    assert scope == "global"
    assert got == {"repo": False, "md": False, "board": False}


def test_a_guest_gets_the_default(app):
    got, scope = resolve(app, {}, None, user_id=None)
    assert got == {"repo": False, "md": False, "board": False}
    assert scope == "global"


def test_a_user_without_the_field_gets_the_default(app):
    """מסמך משתמש ישן, מלפני הפיצ'ר — אין שדה, ואין קריסה."""
    got, _ = resolve(app, {}, {"ui_prefs": {"theme": "classic"}})
    assert got == {"repo": False, "md": False, "board": False}


# ── מסלול ה-API, מול מסד אמיתי בלבד ─────────────────────────────────────

pytestmark_db = pytest.mark.skipif(
    not MONGO_URI,
    reason="דורש מונגו אמיתי; הגדירו NOTE_FONTS_TEST_MONGO_URI",
)


@pytest.fixture
def wired():
    import pymongo

    import webapp.app as wa

    pymongo.MongoClient(MONGO_URI).drop_database("note_fonts_test")
    wa.MONGODB_URL = MONGO_URI
    wa.client = None
    wa.db = None
    wa.app.config["TESTING"] = True
    return wa


def _post(client, body):
    import json

    return client.post("/api/ui_prefs", data=json.dumps(body),
                       content_type="application/json")


def _cookie(res, name):
    for header in res.headers.getlist("Set-Cookie"):
        if header.startswith(name + "="):
            return header.split(";")[0].split("=", 1)[1]
    return None


@pytestmark_db
def test_a_global_write_reaches_the_database(wired):
    users = wired.get_db().users
    users.delete_many({"user_id": 7})
    client = wired.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 7

    res = _post(client, {"note_fonts": {"repo": True, "md": False, "board": True},
                         "note_fonts_scope": "global"})
    assert res.status_code == 200

    # קריאה חוזרת מהמסד, ולא ערך ההחזרה של הראוט
    doc = users.find_one({"user_id": 7}) or {}
    assert doc.get("ui_prefs", {}).get("note_fonts") == {
        "repo": True, "md": False, "board": True}
    assert _cookie(res, "ui_note_fonts") == "101"


@pytestmark_db
def test_a_device_write_never_reaches_the_database(wired):
    """המכשיר מקבל את הערך, והמסד נשאר כפי שהיה.

    הבדיקה על ה-cookie **בתגובה עצמה** ולא על סטטוס 200: השומר
    ``needs_cookie_update`` החזיר 200 בלי קוקיז כשהערכים החדשים לא
    היו ברשימה שלו, וסטטוס לבדו לא היה חושף את זה.
    """
    users = wired.get_db().users
    users.delete_many({"user_id": 7})
    users.insert_one({"user_id": 7, "ui_prefs": {
        "note_fonts": {"repo": False, "md": False, "board": False}}})
    client = wired.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 7

    res = _post(client, {"note_fonts": {"repo": True, "md": True, "board": True},
                         "note_fonts_scope": "device"})
    assert res.status_code == 200

    doc = users.find_one({"user_id": 7}) or {}
    assert doc.get("ui_prefs", {}).get("note_fonts") == {
        "repo": False, "md": False, "board": False}, "ה-DB נדרס"
    assert _cookie(res, "ui_note_fonts") == "111", "המכשיר לא קיבל את הערך"
    assert _cookie(res, "ui_note_fonts_scope") == "device"


@pytestmark_db
def test_a_partial_update_keeps_the_other_surfaces(wired):
    users = wired.get_db().users
    users.delete_many({"user_id": 7})
    users.insert_one({"user_id": 7, "ui_prefs": {
        "note_fonts": {"repo": True, "md": True, "board": True}}})
    client = wired.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 7

    res = _post(client, {"note_fonts": {"md": False}, "note_fonts_scope": "global"})
    assert res.status_code == 200

    doc = users.find_one({"user_id": 7}) or {}
    assert doc.get("ui_prefs", {}).get("note_fonts") == {
        "repo": True, "md": False, "board": True}


@pytestmark_db
def test_a_non_object_payload_is_rejected(wired):
    client = wired.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 7
    res = _post(client, {"note_fonts": "handwriting"})
    assert res.status_code == 400
