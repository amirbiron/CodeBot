"""גודל הטקסט בפתק, כפי שנקבע בעמוד ההגדרות.

ההגדרה חלה על **שני משטחים יחד** — דפדפן הריפו וקובצי Markdown — ויש לה
בורר תחולה משלה, נפרד מזה של כתב היד. הלוחות אינם כאן: להם בורר משלהם
במודאל הלוח, שנשמר ב-``localStorage``.

**מה נבדק כאן, ולמה דווקא זה.** הפיצ'ר עצמו הוא בורר; מה שמסוכן בו הוא
מה שיושב **סביבו**, ושלושת הדברים האלה כבר נשכו בריפו הזה בעבר:

1. ההעדפה מרונדרת לתוך ה-HTML, ולכן היא חייבת להיכנס לוולידטור של
   ה-ETag. בלי זה שינוי ההגדרה מחזיר 304 והדפדפן מציג את הגודל הישן.
2. הפרויקציה שמושכת את מסמך המשתמש ל-ETag מפרטת שדות. שדה שאינו בה
   פשוט אינו נקרא — בשקט.
3. יש קיצור דרך שמדלג על המסד כשהכול הוכרע מ-cookie. הגודל חייב להיכלל
   בהכרעה הזו, אחרת המפתח מחושב לפי ברירת המחדל.

הכרעת התחולה עצמה מחקה את זו של כתב היד ושל ערכת הנושא: cookie של
המכשיר גובר **רק** כשהתחולה היא ``device``; אחרת ה-DB.
"""

import json

import pytest

pytest.importorskip("flask")


@pytest.fixture
def app():
    from webapp.app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app


def resolve(app, cookies, user_doc, user_id=7):
    from webapp.app import _resolve_note_font_size

    header = "; ".join(f"{k}={v}" for k, v in cookies.items())
    with app.test_request_context("/", headers={"Cookie": header}):
        return _resolve_note_font_size(user_id, user_doc)


def _doc(size):
    return {"ui_prefs": {"note_font_size": size}}


# ── דמויות המסד ─────────────────────────────────────────────────────────
#
# מוגדרות כאן, לפני כל מי שמשתמש בהן: גם מסלול ה-API מול דמה וגם רינדור
# עמוד ההגדרות נשענים על אותן שתיים.

class _Cursor(list):
    """מה ש-``find`` מחזיר. עמוד ההגדרות משרשר ``sort``/``limit``."""

    def sort(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def skip(self, *_a, **_k):
        return self


class _AnyCollection:
    """כל שאר האוספים שהעמוד נוגע בהם.

    **החתימות רחבות בכוונה** (``*args, **kwargs``). דמה שמקבלת בדיוק שני
    ארגומנטים נשברת ברגע שהקוד מוסיף ``sort`` או ``projection``, והנפילה
    נבלעת ב-``try`` של ההזרקה — כלומר הבדיקה מדווחת על משהו אחר לגמרי.
    """

    def find_one(self, *_a, **_k):
        return None

    def find(self, *_a, **_k):
        return _Cursor()

    def count_documents(self, *_a, **_k):
        return 0

    def distinct(self, *_a, **_k):
        return []

    def aggregate(self, *_a, **_k):
        return _Cursor()

    def update_one(self, *_a, **_k):
        return type("Result", (), {"matched_count": 0, "modified_count": 0})()


class _Users(_AnyCollection):
    def __init__(self, prefs):
        self.doc = {"user_id": 123, "ui_prefs": dict(prefs)}

    def find_one(self, *_a, **_k):
        return dict(self.doc)


class _PermissiveDB:
    def __init__(self, users):
        self.users = users

    def __getattr__(self, _name):
        return _AnyCollection()


class _CacheDisabled:
    is_enabled = False


# ── הפענוח ──────────────────────────────────────────────────────────────

def test_every_offered_token_decodes_to_itself():
    from webapp.app import NOTE_FONT_SIZE_VALUES, _decode_note_font_size

    for token in NOTE_FONT_SIZE_VALUES:
        assert _decode_note_font_size(token) == token


@pytest.mark.parametrize("bad", [None, 1, 1.5, True, [], {}, b"lg", ("lg",)])
def test_a_non_string_decodes_to_none_and_does_not_raise(bad):
    """**בדיקת הטיפוס לפני כל נגיעה בערך.**

    הערך מגיע מגוף JSON, כלומר יכול להיות מספר, רשימה, מילון או ``null``.
    ``.strip()`` על כל אחד מהם זורק — והמשתמש היה מקבל 500 במקום 400,
    לפני שהוולידציה הספיקה לומר מה לא תקין.
    """
    from webapp.app import _decode_note_font_size

    assert _decode_note_font_size(bad) is None


@pytest.mark.parametrize("bad", ["", "  ", "XL", "LG", "sticky-font-lg",
                                 "__proto__", "constructor", "lg lg", "15px"])
def test_a_corrupt_string_decodes_to_none(bad):
    from webapp.app import _decode_note_font_size

    assert _decode_note_font_size(bad) is None


def test_a_size_that_only_boards_offer_is_rejected():
    """``xl`` קיים במפה שב-``_note_fonts_head.html``, אבל **לא** כאן.

    המפה עונה על "אילו גדלים קיימים"; עמוד ההגדרות מציע שלושה מהם.
    קבלה של ``xl`` הייתה שומרת גודל שאין דרך לבחור בממשק, ואז הבורר
    היה מציג משהו אחר ממה שמוצג בפתק.
    """
    from webapp.app import _decode_note_font_size

    assert _decode_note_font_size("xl") is None


# ── הכרעת התחולה ────────────────────────────────────────────────────────

def test_the_device_cookie_wins_only_in_device_scope(app):
    got, scope = resolve(app, {"ui_note_font_size_scope": "device",
                               "ui_note_font_size": "lg"}, _doc("mid"))
    assert (got, scope) == ("lg", "device")


def test_in_global_scope_the_database_wins_over_the_cookie(app):
    got, scope = resolve(app, {"ui_note_font_size_scope": "global",
                               "ui_note_font_size": "lg"}, _doc("mid"))
    assert (got, scope) == ("mid", "global")


def test_a_device_with_nothing_stored_falls_back_to_the_shared_value(app):
    """"לא נאמר כלום" אינו "נאמר: רגיל" — וזו כל ההכרעה.

    מכשיר במצב ``device`` שעדיין לא בחר גודל ממשיך להציג את הבחירה
    המשותפת. פענוח שהיה מחזיר ברירת מחדל במקום ``None`` היה מאפס אותה.
    """
    got, _ = resolve(app, {"ui_note_font_size_scope": "device"}, _doc("lg"))
    assert got == "lg"


def test_a_corrupt_device_cookie_falls_back_to_the_shared_value(app):
    got, _ = resolve(app, {"ui_note_font_size_scope": "device",
                           "ui_note_font_size": "zzz"}, _doc("mid"))
    assert got == "mid"


def test_the_two_scopes_are_independent(app):
    """הבורר הנפרד הוא כל הנקודה.

    תחולת כתב היד ותחולת הגודל הן שני cookies שונים; ערבוב ביניהם היה
    מעביר בשקט גם את כתב היד למכשיר כשמשנים רק את הגודל.
    """
    got, scope = resolve(app, {"ui_note_fonts_scope": "device",
                               "ui_note_fonts": "111",
                               "ui_note_font_size": "lg"}, _doc("mid"))
    assert (got, scope) == ("mid", "global"), "תחולת כתב היד אינה מכריעה כאן"


def test_a_guest_gets_the_default(app):
    from webapp.app import NOTE_FONT_SIZE_DEFAULT

    got, scope = resolve(app, {}, None, user_id=None)
    assert (got, scope) == (NOTE_FONT_SIZE_DEFAULT, "global")


def test_a_user_without_the_field_gets_the_default(app):
    from webapp.app import NOTE_FONT_SIZE_DEFAULT

    got, _ = resolve(app, {}, {"ui_prefs": {"theme": "classic"}})
    assert got == NOTE_FONT_SIZE_DEFAULT


@pytest.mark.parametrize("prefs", ["broken", 7, [], None])
def test_a_malformed_ui_prefs_does_not_raise(app, prefs):
    """מסמך שנערך ביד — ``ui_prefs`` שאינו אובייקט.

    ל-מחרוזת אין ``.get``, ולכן ``(doc.get('ui_prefs') or {})`` היה זורק
    כאן. הבדיקה עוברת דרך הפונקציה ולא דרך התבנית, כי ההזרקה עוטפת
    ב-``try`` ובולעת — כלומר כשל היה נראה כמו "הגודל חזר לרגיל".
    """
    from webapp.app import NOTE_FONT_SIZE_DEFAULT

    got, _ = resolve(app, {}, {"ui_prefs": prefs})
    assert got == NOTE_FONT_SIZE_DEFAULT


# ── שלוש המלכודות ───────────────────────────────────────────────────────

def test_the_etag_key_changes_with_the_size(app):
    """**המלכודת המרכזית.** ``_note_fonts_head.html`` מרנדר את הגודל לתוך
    ה-HTML; מפתח שאינו נושא אותו מחזיר 304 עם הגודל הישן.
    """
    from webapp.app import _note_fonts_etag_key

    with app.test_request_context("/"):
        normal = _note_fonts_etag_key(7, user_doc=_doc("normal"))
        mid = _note_fonts_etag_key(7, user_doc=_doc("mid"))
        big = _note_fonts_etag_key(7, user_doc=_doc("lg"))

    assert normal != mid != big and normal != big, (normal, mid, big)


def test_the_etag_key_still_changes_with_the_handwriting_setting(app):
    """שתי ההעדפות חיות באותו מפתח — ואחת לא בלעה את השנייה."""
    from webapp.app import _note_fonts_etag_key

    off = {"ui_prefs": {"note_fonts": {"repo": False, "md": False, "board": False},
                        "note_font_size": "mid"}}
    on = {"ui_prefs": {"note_fonts": {"repo": False, "md": True, "board": False},
                       "note_font_size": "mid"}}
    with app.test_request_context("/"):
        assert _note_fonts_etag_key(7, user_doc=off) != _note_fonts_etag_key(7, user_doc=on)


def test_the_etag_projection_carries_the_size_field(app):
    """המסמך שמגיע להילפרי ה-ETag נשלף עם **פרויקציה מפורטת**.

    הבדיקה מדמה את מה שמונגו מחזיר — רק הנתיבים שביקשו — ומוודאת
    שהגודל שרד. שדה שאינו בפרויקציה אינו קורס; הוא פשוט חוזר לברירת
    המחדל, וזה כשל שנראה בדיוק כמו "ההגדרה לא נשמרה".
    """
    from webapp.app import ETAG_USER_PROJECTION, _resolve_note_font_size

    full = {"user_id": 7, "ui_prefs": {"theme": "classic", "note_font_size": "lg",
                                       "editor": "codemirror"}}

    def project(doc, projection):
        out = {}
        for path in projection:
            cur, target, parts = doc, out, path.split(".")
            for part in parts[:-1]:
                if not isinstance(cur, dict) or part not in cur:
                    cur = None
                    break
                cur = cur[part]
                target = target.setdefault(part, {})
            if isinstance(cur, dict) and parts[-1] in cur:
                target[parts[-1]] = cur[parts[-1]]
        return out

    projected = project(full, ETAG_USER_PROJECTION)
    with app.test_request_context("/"):
        got, _ = _resolve_note_font_size(7, projected)
    assert got == "lg", f"הגודל לא שרד את הפרויקציה: {projected}"


def test_the_database_is_not_skipped_while_the_size_still_depends_on_it(app):
    """הקיצור שמדלג על שליפת מסמך המשתמש חייב להתחשב גם בגודל.

    כשהערכה וכתב היד הוכרעו מה-cookie אבל הגודל לא, דילוג היה מחשב את
    מפתח ה-ETag לפי ברירת המחדל — כלומר מפתח שאינו זז אחרי שינוי
    ההגדרה, שזה בדיוק הכשל שהמפתח נועד למנוע.
    """
    from webapp.app import _etag_needs_user_doc

    decided_but_not_size = {
        "ui_theme_scope": "device", "ui_theme": "classic",
        "ui_note_fonts_scope": "device", "ui_note_fonts": "000",
    }
    header = "; ".join(f"{k}={v}" for k, v in decided_but_not_size.items())
    with app.test_request_context("/", headers={"Cookie": header}):
        assert _etag_needs_user_doc() is True, "דילג על המסד בזמן שהגודל תלוי בו"

    everything = dict(decided_but_not_size,
                      **{"ui_note_font_size_scope": "device", "ui_note_font_size": "lg"})
    header = "; ".join(f"{k}={v}" for k, v in everything.items())
    with app.test_request_context("/", headers={"Cookie": header}):
        assert _etag_needs_user_doc() is False, "הכול הוכרע מ-cookie ובכל זאת נשלף"


# ── מסלול ה-API מול דמה, כדי שמלכודת הקוקיז תיבדק בכל סביבה ────────────
#
# **החלק שלא דורש מסד אמיתי.** מה שנבדק כאן הוא **התגובה** — הקוקי שנשלח
# והסטטוס — ולא מה נחת ב-DB. בדיוק בגלל זה זה עובד מול דמה: במצב
# ``device`` הראוט אינו כותב למסד כלל, וזה גם המצב שבו המלכודת חיה.


class _RecordingUsers(_AnyCollection):
    """דמה שמקבלת כל חתימה, ורושמת מה נכתב.

    ``*args, **kwargs`` ולא שני פרמטרים: החתימות ב-``webapp/app.py``
    כוללות פרויקציה, ודמה צרה הייתה נופלת עליה — נפילה שנבלעת ומדווחת
    כמשהו אחר לגמרי.
    """

    def __init__(self):
        self.writes = []

    def update_one(self, _query, update, **_kw):
        self.writes.append(update)
        return type("Result", (), {"matched_count": 1, "modified_count": 1})()


def _post_pref(monkeypatch, body):
    import webapp.app as webapp_app

    users = _RecordingUsers()
    monkeypatch.setattr(webapp_app, "get_db",
                        lambda: _PermissiveDB(users), raising=True)
    with webapp_app.app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 123
            sess["user_data"] = {"id": 123, "first_name": "Test"}
        res = client.post("/api/ui_prefs", data=json.dumps(body),
                          content_type="application/json")
    return res, users


def test_the_cookie_is_sent_even_when_nothing_is_written_to_the_database(monkeypatch):
    """**המלכודת שכבר נשכה כאן פעם, ובדיקה שמסוגלת לתפוס אותה.**

    במצב ``device`` שום דבר אינו נכתב ל-DB, ולכן ``needs_db_update``
    אינו מכסה את הבקשה. ערך שנשכח ברשימת הקוקיז נבנה, עובר ולידציה,
    ואז נזרק בחזרה המוקדמת — **התגובה 200 והקוקי לא נשלח**.

    ולכן הטענה היא על ה-cookie **בתגובה עצמה**; בדיקה שהסתפקה בסטטוס
    200 הייתה עוברת על הבאג במלואו.
    """
    res, users = _post_pref(monkeypatch, {"note_font_size": "lg",
                                          "note_font_size_scope": "device"})

    assert res.status_code == 200
    assert _cookie(res, "ui_note_font_size") == "lg", "הקוקי לא נשלח"
    assert _cookie(res, "ui_note_font_size_scope") == "device"
    assert not users.writes, f"מצב device כתב ל-DB: {users.writes}"


def test_a_global_save_writes_the_field_and_sets_the_cookie(monkeypatch):
    res, users = _post_pref(monkeypatch, {"note_font_size": "mid",
                                          "note_font_size_scope": "global"})

    assert res.status_code == 200
    assert _cookie(res, "ui_note_font_size") == "mid"
    written = [w.get("$set", {}).get("ui_prefs.note_font_size") for w in users.writes]
    assert "mid" in written, f"השדה לא נכתב: {users.writes}"


@pytest.mark.parametrize("bad", ["xl", "zzz", "", 5, None, ["lg"], {"v": "lg"}, True])
def test_an_invalid_size_is_rejected_before_anything_is_written(monkeypatch, bad):
    """דחייה ולא המרה, ולא 500.

    טוקן לא מוכר אינו מוחל בדפדפן — ההחלה מאמתת מול המפה — ולכן שמירה
    שקטה שלו הייתה מציגה למשתמש "נשמר" על גודל שלא ישתנה לעולם. וערך
    שאינו מחרוזת חייב להיעצר בוולידציה, לא לזרוק.
    """
    res, users = _post_pref(monkeypatch, {"note_font_size": bad,
                                          "note_font_size_scope": "global"})

    assert res.status_code == 400, f"{bad!r} התקבל"
    assert res.get_json().get("ok") is False
    assert not users.writes, f"נכתב למסד למרות ה-400: {users.writes}"


def test_a_rejected_size_does_not_take_the_handwriting_down_with_it(monkeypatch):
    """הבקשה נושאת את שתי ההעדפות, ולכן דחייה מפילה גם את השנייה.

    זו התנהגות מכוונת — הכול או כלום, ולא שמירה חלקית שמשאירה את השרת
    עם שני מצבים שנשמרו בזמנים שונים — והבדיקה מקבעת אותה כדי שלא
    תשתנה בשקט.
    """
    res, users = _post_pref(monkeypatch, {
        "note_fonts": {"repo": True, "md": False, "board": False},
        "note_fonts_scope": "global",
        "note_font_size": "nope",
        "note_font_size_scope": "global",
    })

    assert res.status_code == 400
    assert not users.writes, "כתב היד נשמר למרות שהבקשה נדחתה"


# ── מסלול ה-API, מול מסד אמיתי בלבד ─────────────────────────────────────

def _post(client, body):
    return client.post("/api/ui_prefs", data=json.dumps(body),
                       content_type="application/json")


def _cookie(res, name):
    for header in res.headers.getlist("Set-Cookie"):
        if header.startswith(name + "="):
            return header.split(";")[0].split("=", 1)[1]
    return None


def _client(wired_mongo, user_id=7):
    client = wired_mongo.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
    return client


def test_a_global_write_reaches_the_database(wired_mongo):
    users = wired_mongo.get_db().users
    users.delete_many({"user_id": 7})

    res = _post(_client(wired_mongo), {"note_font_size": "mid",
                                       "note_font_size_scope": "global"})
    assert res.status_code == 200

    # קריאה חוזרת מהמסד, ולא ערך ההחזרה של הראוט
    doc = users.find_one({"user_id": 7}) or {}
    assert doc.get("ui_prefs", {}).get("note_font_size") == "mid"
    assert _cookie(res, "ui_note_font_size") == "mid"


def test_a_device_write_sets_the_cookie_and_stays_out_of_the_database(wired_mongo):
    """**זו המלכודת השנייה, והיא כבר נשכה כאן פעם.**

    במצב ``device`` שום דבר אינו נכתב ל-DB, ולכן ``needs_db_update``
    אינו מכסה את הבקשה. ערך שנשכח ברשימת הקוקיז נבנה, עובר ולידציה,
    ואז נזרק בחזרה המוקדמת — התגובה 200 והקוקי פשוט לא נשלח.

    ולכן הבדיקה על ה-cookie **בתגובה עצמה**: בדיקה שהסתפקה בסטטוס 200
    הייתה עוברת על הבאג הזה.
    """
    users = wired_mongo.get_db().users
    users.delete_many({"user_id": 7})

    res = _post(_client(wired_mongo), {"note_font_size": "lg",
                                       "note_font_size_scope": "device"})
    assert res.status_code == 200
    assert _cookie(res, "ui_note_font_size") == "lg", "הקוקי לא נשלח"
    assert _cookie(res, "ui_note_font_size_scope") == "device"

    doc = users.find_one({"user_id": 7}) or {}
    assert "note_font_size" not in doc.get("ui_prefs", {}), "מצב device כתב ל-DB"


@pytest.mark.parametrize("bad", ["xl", "zzz", "", 5, None, ["lg"], {"v": "lg"}, True])
def test_an_invalid_size_is_rejected_and_nothing_is_written(wired_mongo, bad):
    users = wired_mongo.get_db().users
    users.delete_many({"user_id": 7})
    users.insert_one({"user_id": 7, "ui_prefs": {"note_font_size": "mid"}})

    res = _post(_client(wired_mongo), {"note_font_size": bad,
                                       "note_font_size_scope": "global"})
    assert res.status_code == 400, f"{bad!r} התקבל"

    doc = users.find_one({"user_id": 7}) or {}
    assert doc.get("ui_prefs", {}).get("note_font_size") == "mid", "הערך הקיים נדרס"


def test_the_size_and_the_handwriting_are_saved_in_one_request(wired_mongo):
    """העמוד שולח את שתיהן יחד; שתיהן חייבות לנחות."""
    users = wired_mongo.get_db().users
    users.delete_many({"user_id": 7})

    res = _post(_client(wired_mongo), {
        "note_fonts": {"repo": True, "md": False, "board": False},
        "note_fonts_scope": "global",
        "note_font_size": "lg",
        "note_font_size_scope": "global",
    })
    assert res.status_code == 200

    prefs = (users.find_one({"user_id": 7}) or {}).get("ui_prefs", {})
    assert prefs.get("note_font_size") == "lg"
    assert prefs.get("note_fonts") == {"repo": True, "md": False, "board": False}


def test_each_scope_only_moves_its_own_value(wired_mongo):
    """כתב היד לכל המכשירים, הגודל רק כאן — ובלי שאחד ידרוס את השני."""
    users = wired_mongo.get_db().users
    users.delete_many({"user_id": 7})

    res = _post(_client(wired_mongo), {
        "note_fonts": {"repo": True, "md": True, "board": False},
        "note_fonts_scope": "global",
        "note_font_size": "mid",
        "note_font_size_scope": "device",
    })
    assert res.status_code == 200

    prefs = (users.find_one({"user_id": 7}) or {}).get("ui_prefs", {})
    assert prefs.get("note_fonts") == {"repo": True, "md": True, "board": False}
    assert "note_font_size" not in prefs, "הגודל נכתב ל-DB למרות device"
    assert _cookie(res, "ui_note_font_size") == "mid"


# ── הבורר בעמוד ההגדרות ─────────────────────────────────────────────────
#
# **הרינדור נבדק ולא רק ה-API.** ``selected`` נקבע ב-Jinja, ולכן עמוד
# שנטען מציג את הבחירה הנוכחית בלי קפיצה אחרי טעינת JS. ולוגיקה של
# ``{% if %}`` היא בדיוק המקום שבו ערך שלישי נופל בין הכיסאות.


def _render_settings(monkeypatch, prefs):
    import webapp.app as webapp_app

    monkeypatch.setattr(webapp_app, "get_db",
                        lambda: _PermissiveDB(_Users(prefs)), raising=True)
    monkeypatch.setattr(webapp_app, "cache", _CacheDisabled(), raising=True)
    with webapp_app.app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 123
            sess["user_data"] = {"id": 123, "first_name": "Test"}
        res = client.get("/settings")
        assert res.status_code == 200
        return res.get_data(as_text=True)


def _selected_option(html, select_id):
    """הערך של ה-``<option>`` שמסומן ``selected`` בתוך בורר מסוים."""
    import re

    at = html.index(f'id="{select_id}"')
    block = html[at:html.index("</select>", at)]
    marked = re.findall(r'<option value="([^"]+)"[^>]*\bselected\b', block)
    assert len(marked) == 1, f"{select_id}: סומנו {len(marked)} אפשרויות"
    return marked[0]


@pytest.mark.parametrize("stored,expected", [
    (None, "normal"),
    ("normal", "normal"),
    ("mid", "mid"),
    ("lg", "lg"),
    ("xl", "normal"),        # קיים במפה, לא מוצע כאן
    ("garbage", "normal"),
])
def test_the_settings_select_reflects_the_saved_size(monkeypatch, stored, expected):
    prefs = {} if stored is None else {"note_font_size": stored}
    html = _render_settings(monkeypatch, prefs)

    assert 'id="settingsNoteFontSizeSelect"' in html, "הבורר אינו מגיע לעמוד"
    assert _selected_option(html, "settingsNoteFontSizeSelect") == expected


@pytest.mark.parametrize("scope,expected", [
    (None, "global"), ("device", "device"), ("global", "global"),
])
def test_the_size_scope_select_is_independent_of_the_handwriting_scope(
    monkeypatch, scope, expected
):
    """בורר התחולה של הגודל קורא את ה-cookie שלו בלבד.

    שני הבוררים נראים זהים בעמוד, ולכן ערבוב ביניהם היה נראה תקין
    לחלוטין — עד שמישהו משנה אחד ומגלה שגם השני זז.
    """
    import webapp.app as webapp_app

    monkeypatch.setattr(webapp_app, "get_db",
                        lambda: _PermissiveDB(_Users({})), raising=True)
    monkeypatch.setattr(webapp_app, "cache", _CacheDisabled(), raising=True)
    with webapp_app.app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 123
            sess["user_data"] = {"id": 123, "first_name": "Test"}
        # תחולת **כתב היד** על device, ותחולת הגודל כפי שהפרמטר אומר
        client.set_cookie("ui_note_fonts_scope", "device")
        if scope:
            client.set_cookie("ui_note_font_size_scope", scope)
        html = client.get("/settings").get_data(as_text=True)

    assert _selected_option(html, "settingsNoteFontSizeScopeSelect") == expected
    assert _selected_option(html, "noteFontsScopeSelect") == "device", (
        "תחולת כתב היד השתנתה מהבורר של הגודל"
    )
